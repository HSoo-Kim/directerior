from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import suppress
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from directerior_core import (
    Config,
    DirecteriorError,
    Leaf,
    hdd_project_path,
    prune_empty_upward,
    section_path,
)
from directerior_guards import require_approval
from directerior_history import (
    MigrationRecord,
    OperationRecord,
    list_operation_records,
    list_records,
    new_operation_id,
    save_operation_record,
)
from directerior_storage import (
    TreeSnapshot,
    bytes_snapshot,
    copy_file_verified,
    copy_tree_verified,
    file_snapshot,
    is_offloaded,
    link_target,
    make_link,
    remove_link,
    require_capacity,
    require_disjoint_paths,
    require_plain_tree,
    same_volume,
    tree_snapshot,
    tree_snapshot_no_follow,
)


def _git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _new_record(
    root: Path, operation_type: str, details: dict[str, object], operation_id: str | None = None
) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id or new_operation_id(),
        operation_type=operation_type,
        project_root=str(root),
        created_at=datetime.now(timezone.utc).isoformat(),
        git_head=_git_head(root),
        state="prepared",
        details=details,
    )


def _save(record: OperationRecord, state: str) -> OperationRecord:
    updated = replace(record, state=state)
    save_operation_record(updated)
    return updated


def _path(record: OperationRecord, name: str) -> Path:
    value = record.details.get(name)
    if not isinstance(value, str):
        raise DirecteriorError(f"invalid {record.operation_type} journal path: {name}")
    return Path(value)

def _strings(record: OperationRecord, name: str) -> list[str]:
    value = record.details.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DirecteriorError(f"invalid {record.operation_type} journal list: {name}")
    return value


def _named_snapshot(record: OperationRecord, name: str) -> TreeSnapshot:
    value = record.details.get(name)
    if not isinstance(value, dict):
        raise DirecteriorError(f"invalid {record.operation_type} journal snapshot: {name}")
    try:
        return TreeSnapshot(
            file_count=int(value["file_count"]),
            byte_count=int(value["byte_count"]),
            digest=str(value["digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DirecteriorError(
            f"invalid {record.operation_type} journal snapshot: {name}"
        ) from exc


def _snapshot(record: OperationRecord) -> TreeSnapshot:
    return _named_snapshot(record, "snapshot")


def _matches_tree(path: Path, snapshot: TreeSnapshot) -> bool:
    try:
        return path.is_dir() and not is_offloaded(path) and tree_snapshot(path) == snapshot
    except (OSError, DirecteriorError):
        return False

def _matches_tree_no_follow(path: Path, snapshot: TreeSnapshot) -> bool:
    try:
        return (
            path.is_dir()
            and not is_offloaded(path)
            and tree_snapshot_no_follow(path) == snapshot
        )
    except OSError:
        return False


def _matches_file(path: Path, snapshot: TreeSnapshot) -> bool:
    try:
        return path.is_file() and not is_offloaded(path) and file_snapshot(path) == snapshot
    except OSError:
        return False


def _matches_data(path: Path, snapshot: TreeSnapshot, is_directory: bool) -> bool:
    return _matches_tree(path, snapshot) if is_directory else _matches_file(path, snapshot)


def _absent(path: Path) -> bool:
    return not path.exists() and not is_offloaded(path)


def _conflict(record: OperationRecord, *paths: Path) -> DirecteriorError:
    joined = ", ".join(str(path) for path in paths)
    return DirecteriorError(
        f"recovery conflict for {record.operation_type} {record.operation_id} "
        f"in state {record.state}: {joined}"
    )


def start_offload(
    root: Path,
    _config: Config,
    names: tuple[str, ...],
    results: Path,
    target: Path,
) -> OperationRecord:
    require_plain_tree(results, "offload")
    require_disjoint_paths(results, target, "offload")
    if target.exists() or is_offloaded(target):
        raise DirecteriorError(f"target already exists: {target}")
    snapshot = require_capacity(results, target)
    record = _new_record(
        root,
        "offload",
        {
            "names": list(names),
            "source": str(results),
            "target": str(target),
            "snapshot": asdict(snapshot),
            "link_intent": True,
            "transfer_mode": "copy",
        },
    )
    save_operation_record(record)
    return continue_offload(record)


def continue_offload(record: OperationRecord) -> OperationRecord:
    source = _path(record, "source")
    target = _path(record, "target")
    snapshot = _snapshot(record)
    while record.state != "committed":
        if record.state == "prepared":
            if _matches_tree(source, snapshot) and _absent(target):
                copy_tree_verified(source, target, "offload")
            elif not (_matches_tree(source, snapshot) and _matches_tree(target, snapshot)):
                raise _conflict(record, source, target)
            record = _save(record, "copied")
        elif record.state == "copied":
            if not (_matches_tree(source, snapshot) and _matches_tree(target, snapshot)):
                raise _conflict(record, source, target)
            record = _save(record, "verified")
        elif record.state == "verified":
            if _matches_tree(source, snapshot) and _matches_tree(target, snapshot):
                shutil.rmtree(source)
            elif not (_absent(source) and _matches_tree(target, snapshot)):
                raise _conflict(record, source, target)
            record = _save(record, "source_removed")
        elif record.state == "source_removed":
            if _absent(source) and _matches_tree(target, snapshot):
                make_link(source, target)
            elif not (
                link_target(source) == target.resolve(strict=False)
                and _matches_tree(target, snapshot)
            ):
                raise _conflict(record, source, target)
            record = _save(record, "linked")
        elif record.state == "linked":
            if link_target(source) != target.resolve(strict=False) or not _matches_tree(
                target, snapshot
            ):
                raise _conflict(record, source, target)
            record = _save(record, "committed")
        else:
            raise _conflict(record, source, target)
    return record


def start_restore(
    root: Path,
    config: Config,
    names: tuple[str, ...],
    link: Path,
    source: Path,
) -> OperationRecord:
    if link_target(link) != source.resolve(strict=False) or not source.is_dir():
        raise DirecteriorError(f"not offloaded to expected target: {link}")
    require_plain_tree(source, "restore")
    operation_id = new_operation_id()
    staging = link.with_name(f".{link.name}.restore-{operation_id}")
    require_disjoint_paths(source, staging, "restore")
    snapshot = require_capacity(source, staging)
    record = _new_record(
        root,
        "restore",
        {
            "names": list(names),
            "link": str(link),
            "source": str(source),
            "staging": str(staging),
            "snapshot": asdict(snapshot),
            "link_intent": False,
            "transfer_mode": "copy",
            "hdd_root": str(config.hdd_root),
        },
        operation_id,
    )
    save_operation_record(record)
    return continue_restore(record)


def _preflight_restore(
    record: OperationRecord,
    link: Path,
    source: Path,
    staging: Path,
    snapshot: TreeSnapshot,
) -> None:
    linked = link_target(link) == source.resolve(strict=False)
    link_absent = _absent(link)
    local_ready = _matches_tree(link, snapshot)
    source_ready = _matches_tree(source, snapshot)
    staging_ready = _matches_tree(staging, snapshot)
    staging_absent = _absent(staging)
    ready = {
        "prepared": linked
        and source_ready
        and (staging_absent or staging_ready),
        "copied": linked and source_ready and staging_ready,
        "verified": source_ready
        and staging_ready
        and (linked or link_absent),
        "link_removed": source_ready
        and (
            link_absent
            and staging_ready
            or local_ready
            and staging_absent
        ),
        "local_installed": local_ready
        and staging_absent
        and (source_ready or _absent(source)),
        "hdd_removed": local_ready and staging_absent and _absent(source),
    }.get(record.state, False)
    if not ready:
        raise _conflict(record, link, source, staging)


def continue_restore(record: OperationRecord) -> OperationRecord:
    link = _path(record, "link")
    source = _path(record, "source")
    staging = _path(record, "staging")
    snapshot = _snapshot(record)
    _preflight_restore(record, link, source, staging, snapshot)
    while record.state != "committed":
        if record.state == "prepared":
            expected_link = link_target(link) == source.resolve(strict=False)
            if expected_link and _matches_tree(source, snapshot) and _absent(staging):
                copy_tree_verified(source, staging, "restore")
            elif not (
                expected_link
                and _matches_tree(source, snapshot)
                and _matches_tree(staging, snapshot)
            ):
                raise _conflict(record, link, source, staging)
            record = _save(record, "copied")
        elif record.state == "copied":
            if not (_matches_tree(source, snapshot) and _matches_tree(staging, snapshot)):
                raise _conflict(record, source, staging)
            record = _save(record, "verified")
        elif record.state == "verified":
            if link_target(link) == source.resolve(strict=False):
                remove_link(link)
            elif not _absent(link):
                raise _conflict(record, link)
            record = _save(record, "link_removed")
        elif record.state == "link_removed":
            if _absent(link) and _matches_tree(staging, snapshot):
                staging.rename(link)
            elif not (_matches_tree(link, snapshot) and _absent(staging)):
                raise _conflict(record, link, staging)
            record = _save(record, "local_installed")
        elif record.state == "local_installed":
            if _matches_tree(link, snapshot) and _matches_tree(source, snapshot):
                shutil.rmtree(source)
            elif not (_matches_tree(link, snapshot) and _absent(source)):
                raise _conflict(record, link, source)
            record = _save(record, "hdd_removed")
        elif record.state == "hdd_removed":
            if not (_matches_tree(link, snapshot) and _absent(source)):
                raise _conflict(record, link, source)
            hdd_root = _path(record, "hdd_root")
            prune_empty_upward(source.parent, hdd_root)
            record = _save(record, "committed")
        else:
            raise _conflict(record, link, source, staging)
    return record


def _updated_manifest_content(
    path: Path, hierarchy: list[str] | tuple[str, ...], names: list[str] | tuple[str, ...]
) -> bytes:
    manifest = path / "manifest.json"
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["levels"] = dict(zip(hierarchy, names, strict=True))
    return (json.dumps(raw, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _update_manifest(path: Path, hierarchy: list[str], names: list[str]) -> None:
    (path / "manifest.json").write_bytes(_updated_manifest_content(path, hierarchy, names))


def _matches_tree_no_follow_excluding(
    path: Path, snapshot: TreeSnapshot, exclude: Path | tuple[Path, ...] | None = None
) -> bool:
    try:
        return (
            path.is_dir()
            and not is_offloaded(path)
            and tree_snapshot_no_follow(path, exclude) == snapshot
        )
    except OSError:
        return False


def start_rename(
    root: Path,
    config: Config,
    old_names: tuple[str, ...],
    new_names: tuple[str, ...],
    old_leaf: Path,
    new_leaf: Path,
    old_results: Path,
    old_target: Path,
    new_target: Path,
) -> OperationRecord:
    offloaded = is_offloaded(old_results)
    if offloaded:
        require_plain_tree(old_target, "rename")
    else:
        require_plain_tree(old_leaf, "rename")
    local_snapshot = tree_snapshot_no_follow(old_leaf)
    unlinked_snapshot = (
        tree_snapshot_no_follow(old_leaf, old_results) if offloaded else local_snapshot
    )
    manifest = old_leaf / "manifest.json"
    content_exclusions = (manifest, old_results) if offloaded else (manifest,)
    content_snapshot = tree_snapshot_no_follow(old_leaf, content_exclusions)
    manifest_snapshot = bytes_snapshot(
        _updated_manifest_content(old_leaf, config.hierarchy, new_names)
    )
    hdd_snapshot = tree_snapshot(old_target) if offloaded else None
    record = _new_record(
        root,
        "rename",
        {
            "old_names": list(old_names),
            "new_names": list(new_names),
            "old_leaf": str(old_leaf),
            "new_leaf": str(new_leaf),
            "old_results": str(old_results),
            "new_results": str(new_leaf / config.sections["results"]),
            "old_target": str(old_target),
            "new_target": str(new_target),
            "snapshot": asdict(hdd_snapshot if hdd_snapshot is not None else local_snapshot),
            "local_snapshot": asdict(local_snapshot),
            "unlinked_snapshot": asdict(unlinked_snapshot),
            "content_snapshot": asdict(content_snapshot),
            "manifest_snapshot": asdict(manifest_snapshot),
            "hdd_snapshot": asdict(hdd_snapshot) if hdd_snapshot is not None else None,
            "offloaded": offloaded,
            "hierarchy": list(config.hierarchy),
            "hdd_root": str(config.hdd_root),
        },
    )
    save_operation_record(record)
    return continue_rename(record)


def continue_rename(record: OperationRecord) -> OperationRecord:
    old_leaf = _path(record, "old_leaf")
    new_leaf = _path(record, "new_leaf")
    old_results = _path(record, "old_results")
    new_results = _path(record, "new_results")
    old_target = _path(record, "old_target")
    new_target = _path(record, "new_target")
    required_snapshots = (
        "local_snapshot",
        "unlinked_snapshot",
        "content_snapshot",
        "manifest_snapshot",
    )
    if not all(name in record.details for name in required_snapshots):
        raise DirecteriorError(
            "rename journal lacks exact local snapshots; refusing unsafe recovery"
        )
    local_snapshot = _named_snapshot(record, "local_snapshot")
    unlinked_snapshot = _named_snapshot(record, "unlinked_snapshot")
    content_snapshot = _named_snapshot(record, "content_snapshot")
    manifest_snapshot = _named_snapshot(record, "manifest_snapshot")
    offloaded = record.details.get("offloaded") is True
    hdd_snapshot = _named_snapshot(record, "hdd_snapshot") if offloaded else None
    hierarchy = _strings(record, "hierarchy")
    new_names = _strings(record, "new_names")
    new_manifest = new_leaf / "manifest.json"
    new_content_exclusions = (
        (new_manifest, new_results) if offloaded else (new_manifest,)
    )

    def old_hdd_ready() -> bool:
        return (
            not offloaded
            or hdd_snapshot is not None
            and _matches_tree(old_target, hdd_snapshot)
            and _absent(new_target)
        )

    def new_hdd_ready() -> bool:
        return (
            not offloaded
            or hdd_snapshot is not None
            and _matches_tree(new_target, hdd_snapshot)
            and _absent(old_target)
        )

    def old_unlinked_ready() -> bool:
        return _matches_tree_no_follow_excluding(
            old_leaf,
            unlinked_snapshot,
            old_results if offloaded else None,
        )

    def new_unlinked_ready() -> bool:
        return _matches_tree_no_follow_excluding(
            new_leaf,
            unlinked_snapshot,
            new_results if offloaded else None,
        )

    while record.state != "committed":
        if record.state == "prepared":
            if not old_hdd_ready() or not _absent(new_leaf):
                raise _conflict(record, old_leaf, new_leaf, old_target, new_target)
            if offloaded:
                if _matches_tree_no_follow(old_leaf, local_snapshot):
                    if link_target(old_results) != old_target.resolve(strict=False):
                        raise _conflict(record, old_results, old_target)
                    remove_link(old_results)
                elif not old_unlinked_ready():
                    raise _conflict(record, old_leaf, old_results)
            elif not _matches_tree_no_follow(old_leaf, local_snapshot):
                raise _conflict(record, old_leaf)
            record = _save(record, "link_removed")
        elif record.state == "link_removed":
            if not old_hdd_ready():
                raise _conflict(record, old_target, new_target)
            if old_unlinked_ready() and _absent(new_leaf):
                new_leaf.parent.mkdir(parents=True, exist_ok=True)
                old_leaf.rename(new_leaf)
            elif not (new_unlinked_ready() and _absent(old_leaf)):
                raise _conflict(record, old_leaf, new_leaf)
            record = _save(record, "local_renamed")
        elif record.state == "local_renamed":
            if not (new_unlinked_ready() and _absent(old_leaf)):
                raise _conflict(record, old_leaf, new_leaf)
            if offloaded:
                if old_hdd_ready():
                    new_target.parent.mkdir(parents=True, exist_ok=True)
                    old_target.rename(new_target)
                elif not new_hdd_ready():
                    raise _conflict(record, old_target, new_target)
            record = _save(record, "hdd_renamed")
        elif record.state == "hdd_renamed":
            if not new_hdd_ready() or not _absent(old_leaf):
                raise _conflict(record, old_leaf, new_leaf, old_target, new_target)
            if offloaded:
                if new_unlinked_ready() and _absent(new_results):
                    make_link(new_results, new_target)
                elif not (
                    link_target(new_results) == new_target.resolve(strict=False)
                    and _matches_tree_no_follow_excluding(
                        new_leaf, unlinked_snapshot, new_results
                    )
                ):
                    raise _conflict(record, new_leaf, new_results, new_target)
            elif not _matches_tree_no_follow(new_leaf, local_snapshot):
                raise _conflict(record, new_leaf)
            record = _save(record, "linked")
        elif record.state == "linked":
            if not new_hdd_ready() or (
                offloaded and link_target(new_results) != new_target.resolve(strict=False)
            ):
                raise _conflict(record, new_leaf, new_results, new_target)
            if _matches_file(new_manifest, manifest_snapshot):
                if not _matches_tree_no_follow_excluding(
                    new_leaf, content_snapshot, new_content_exclusions
                ):
                    raise _conflict(record, new_leaf)
            else:
                if not _matches_tree_no_follow_excluding(
                    new_leaf,
                    unlinked_snapshot,
                    new_results if offloaded else None,
                ):
                    raise _conflict(record, new_leaf)
                _update_manifest(new_leaf, hierarchy, new_names)
                if not _matches_file(new_manifest, manifest_snapshot):
                    raise _conflict(record, new_manifest)
            record = _save(record, "manifest_updated")
        elif record.state == "manifest_updated":
            if (
                not new_hdd_ready()
                or offloaded
                and link_target(new_results) != new_target.resolve(strict=False)
                or not _matches_file(new_manifest, manifest_snapshot)
                or not _matches_tree_no_follow_excluding(
                    new_leaf, content_snapshot, new_content_exclusions
                )
            ):
                raise _conflict(record, new_leaf, new_results, new_target)
            record = _save(record, "committed")
        else:
            raise _conflict(record, old_leaf, new_leaf)
    return record


def start_adopt(
    root: Path,
    source: Path,
    destination: Path,
    link_back: bool,
) -> OperationRecord:
    if destination.exists() or is_offloaded(destination):
        raise DirecteriorError(f"destination already exists: {destination}")
    require_disjoint_paths(source, destination, "adopt")
    is_directory = source.is_dir()
    if is_directory:
        require_plain_tree(source, "adopt")
        snapshot = tree_snapshot(source)
    else:
        snapshot = file_snapshot(source)
    mode = "rename" if same_volume(source, destination) else "copy"
    record = _new_record(
        root,
        "adopt",
        {
            "source": str(source),
            "destination": str(destination),
            "snapshot": asdict(snapshot),
            "is_directory": is_directory,
            "link_intent": link_back,
            "transfer_mode": mode,
        },
    )
    save_operation_record(record)
    return continue_adopt(record)


def continue_adopt(record: OperationRecord) -> OperationRecord:
    source = _path(record, "source")
    destination = _path(record, "destination")
    snapshot = _snapshot(record)
    is_directory = record.details.get("is_directory") is True
    link_back = record.details.get("link_intent") is True
    mode = record.details.get("transfer_mode")
    while record.state != "committed":
        if record.state == "prepared":
            source_matches = _matches_data(source, snapshot, is_directory)
            destination_matches = _matches_data(destination, snapshot, is_directory)
            if source_matches and _absent(destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                if mode == "rename":
                    source.rename(destination)
                elif is_directory:
                    copy_tree_verified(source, destination, "adopt")
                else:
                    copy_file_verified(source, destination, "adopt")
            elif not (
                destination_matches
                and (
                    mode == "rename"
                    and _absent(source)
                    or mode == "copy"
                    and source_matches
                )
            ):
                raise _conflict(record, source, destination)
            record = _save(record, "destination_ready")
        elif record.state == "destination_ready":
            if not _matches_data(destination, snapshot, is_directory):
                raise _conflict(record, destination)
            if mode == "copy" and not _matches_data(source, snapshot, is_directory):
                raise _conflict(record, source)
            record = _save(record, "verified")
        elif record.state == "verified":
            # Never delete the source unless the destination still holds a
            # verified copy: it may have changed between states.
            if not _matches_data(destination, snapshot, is_directory):
                raise _conflict(record, source, destination)
            if mode == "copy" and _matches_data(source, snapshot, is_directory):
                shutil.rmtree(source) if is_directory else source.unlink()
            elif mode == "copy" and not _absent(source):
                raise _conflict(record, source)
            record = _save(record, "source_removed")
        elif record.state == "source_removed":
            destination_matches = _matches_data(destination, snapshot, is_directory)
            linked_already = (
                link_back
                and link_target(source) == destination.resolve(strict=False)
            )
            if not destination_matches or not (_absent(source) or linked_already):
                raise _conflict(record, source, destination)
            if link_back and not linked_already:
                make_link(source, destination)
            record = _save(record, "linked")
        elif record.state == "linked":
            if not _matches_data(destination, snapshot, is_directory):
                raise _conflict(record, destination)
            if link_back and link_target(source) != destination.resolve(strict=False):
                raise _conflict(record, source, destination)
            record = _save(record, "committed")
        else:
            raise _conflict(record, source, destination)
    return record


def start_remove(
    root: Path,
    config: Config,
    names: tuple[str, ...],
    leaf: Path,
    target: Path,
    purge: bool,
) -> OperationRecord:
    operation_id = new_operation_id()
    results = section_path(Leaf(names, leaf), config, "results")
    offloaded = is_offloaded(results)
    trash = (
        config.hdd_root
        / ".trash"
        / hdd_project_path(config, root).name
        / operation_id
    )
    local_trash = trash / "local"
    hdd_trash = trash / "hdd"
    local_snapshot = tree_snapshot_no_follow(leaf, results if offloaded else None)
    hdd_exists = target.is_dir() and not is_offloaded(target)
    hdd_snapshot = None
    if hdd_exists:
        require_plain_tree(target, "rm")
        hdd_snapshot = asdict(tree_snapshot(target))
    if not purge and not same_volume(leaf, local_trash):
        # A cross-volume trash move is a verified copy, which cannot carry
        # nested links; refuse before the HDD copy or managed link is touched.
        require_plain_tree(leaf, "rm", results if offloaded else None)
    record = _new_record(
        root,
        "rm",
        {
            "names": list(names),
            "leaf": str(leaf),
            "target": str(target),
            "local_trash": str(local_trash),
            "hdd_trash": str(hdd_trash),
            "purge": purge,
            "offloaded": offloaded,
            "results": str(results),
            "hdd_root": str(config.hdd_root),
            "local_snapshot": asdict(local_snapshot),
            "hdd_existed": hdd_exists,
            "hdd_snapshot": hdd_snapshot,
        },
        operation_id,
    )
    if purge:
        record = replace(record, state="purge_started")
        save_operation_record(record)
        if offloaded:
            remove_link(results)
        if leaf.is_dir():
            shutil.rmtree(leaf)
        if target.is_dir():
            shutil.rmtree(target)
        return _save(record, "committed")
    save_operation_record(record)
    return continue_remove(record)


def _preflight_remove(
    record: OperationRecord,
    leaf: Path,
    target: Path,
    local_trash: Path,
    hdd_trash: Path,
    results: Path,
    local_snapshot: TreeSnapshot,
    hdd_snapshot: TreeSnapshot | None,
    hdd_existed: bool,
    offloaded: bool,
) -> None:
    hdd_before = (
        _matches_tree(target, hdd_snapshot) and _absent(hdd_trash)
        if hdd_existed and hdd_snapshot is not None
        else _absent(target) and _absent(hdd_trash)
    )
    hdd_after = (
        _absent(target) and _matches_tree(hdd_trash, hdd_snapshot)
        if hdd_existed and hdd_snapshot is not None
        else _absent(target) and _absent(hdd_trash)
    )
    local_linked = (
        _matches_tree_no_follow_excluding(leaf, local_snapshot, results)
        and link_target(results) == target.resolve(strict=False)
        if offloaded
        else _matches_tree_no_follow(leaf, local_snapshot)
    )
    local_unlinked = (
        offloaded
        and _matches_tree_no_follow_excluding(leaf, local_snapshot, results)
        and _absent(results)
    )
    local_before = (local_linked or local_unlinked) and _absent(local_trash)
    copied_source = local_unlinked if offloaded else local_linked
    local_copied = copied_source and _matches_tree_no_follow(
        local_trash, local_snapshot
    )
    local_after = _absent(leaf) and _matches_tree_no_follow(
        local_trash, local_snapshot
    )
    ready = {
        "prepared": (hdd_before or hdd_after)
        and local_linked
        and _absent(local_trash),
        "hdd_trashed": hdd_after and (local_before or local_copied or local_after),
        "local_trashed": hdd_after and local_after,
    }.get(record.state, False)
    if not ready:
        raise _conflict(record, leaf, target, local_trash, hdd_trash, results)


def continue_remove(record: OperationRecord) -> OperationRecord:
    leaf = _path(record, "leaf")
    target = _path(record, "target")
    local_trash = _path(record, "local_trash")
    hdd_trash = _path(record, "hdd_trash")
    local_snapshot = _named_snapshot(record, "local_snapshot")
    hdd_existed = record.details.get("hdd_existed") is True
    offloaded = record.details.get("offloaded") is True
    results = _path(record, "results")
    hdd_snapshot = (
        _named_snapshot(record, "hdd_snapshot") if hdd_existed else None
    )
    _preflight_remove(
        record,
        leaf,
        target,
        local_trash,
        hdd_trash,
        results,
        local_snapshot,
        hdd_snapshot,
        hdd_existed,
        offloaded,
    )
    while record.state != "committed":
        if record.state == "prepared":
            source_ready = (
                hdd_snapshot is not None
                and _matches_tree(target, hdd_snapshot)
                and _absent(hdd_trash)
            )
            next_ready = (
                hdd_snapshot is not None
                and _absent(target)
                and _matches_tree(hdd_trash, hdd_snapshot)
            )
            no_hdd = not hdd_existed and _absent(target) and _absent(hdd_trash)
            if source_ready:
                hdd_trash.parent.mkdir(parents=True, exist_ok=True)
                target.rename(hdd_trash)
            elif not (next_ready or no_hdd):
                raise _conflict(record, target, hdd_trash)
            record = _save(record, "hdd_trashed")
        elif record.state == "hdd_trashed":
            hdd_ready = (
                hdd_snapshot is not None
                and _absent(target)
                and _matches_tree(hdd_trash, hdd_snapshot)
                or not hdd_existed
                and _absent(target)
                and _absent(hdd_trash)
            )
            if offloaded:
                if link_target(results) == target.resolve(strict=False):
                    remove_link(results)
                elif not _absent(results):
                    raise _conflict(record, results, target)
            source_ready = _matches_tree_no_follow(
                leaf, local_snapshot
            ) and _absent(local_trash)
            next_ready = _absent(leaf) and _matches_tree_no_follow(
                local_trash, local_snapshot
            )
            copied_ready = _matches_tree_no_follow(
                leaf, local_snapshot
            ) and _matches_tree_no_follow(local_trash, local_snapshot)
            if not hdd_ready:
                raise _conflict(record, target, hdd_trash)
            if source_ready:
                local_trash.parent.mkdir(parents=True, exist_ok=True)
                if same_volume(leaf, local_trash):
                    leaf.rename(local_trash)
                else:
                    copy_tree_verified(leaf, local_trash, "rm")
                    shutil.rmtree(leaf)
            elif copied_ready:
                shutil.rmtree(leaf)
            elif not next_ready:
                raise _conflict(record, leaf, local_trash)
            record = _save(record, "local_trashed")
        elif record.state == "local_trashed":
            if not (
                _absent(leaf)
                and _matches_tree_no_follow(local_trash, local_snapshot)
            ):
                raise _conflict(record, leaf, local_trash)
            if hdd_existed and (
                hdd_snapshot is None
                or not _absent(target)
                or not _matches_tree(hdd_trash, hdd_snapshot)
            ):
                raise _conflict(record, target, hdd_trash)
            record = _save(record, "committed")
        else:
            raise _conflict(record, leaf, target)
    return record


def _continue_operation(record: OperationRecord) -> OperationRecord:
    continuations = {
        "offload": continue_offload,
        "restore": continue_restore,
        "rename": continue_rename,
        "adopt": continue_adopt,
        "rm": continue_remove,
    }
    continuation = continuations.get(record.operation_type)
    if continuation is None:
        raise DirecteriorError(f"unsupported recovery operation: {record.operation_type}")
    return continuation(record)

def _move_verified(source: Path, target: Path, is_directory: bool, operation: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if same_volume(source, target):
        source.rename(target)
        return
    if is_directory:
        copy_tree_verified(source, target, operation)
        shutil.rmtree(source)
    else:
        copy_file_verified(source, target, operation)
        source.unlink()


def undo_operation(root: Path, operation_id: str, approved: bool) -> OperationRecord:
    require_approval(approved, "undo")
    records = list_operation_records(root)
    if operation_id == "latest":
        record = next(
            (candidate for candidate in records if candidate.state == "committed"),
            None,
        )
    else:
        record = next(
            (candidate for candidate in records if candidate.operation_id == operation_id),
            None,
        )
    if record is None:
        raise DirecteriorError(f"operation history not found: {operation_id}")
    if record.state != "committed":
        raise DirecteriorError(f"cannot undo operation in state: {record.state}")

    if record.operation_type == "adopt":
        source = _path(record, "source")
        destination = _path(record, "destination")
        snapshot = _snapshot(record)
        is_directory = record.details.get("is_directory") is True
        linked_back = record.details.get("link_intent") is True
        if not _matches_data(destination, snapshot, is_directory):
            raise DirecteriorError(f"changed since adopt: {destination}")
        if linked_back:
            if link_target(source) != destination.resolve(strict=False):
                raise DirecteriorError(f"changed since adopt: {source}")
            remove_link(source)
        if not _absent(source):
            raise DirecteriorError(f"restore target already exists: {source}")
        _move_verified(destination, source, is_directory, "undo adopt")
    elif record.operation_type == "rm":
        if record.details.get("purge") is True:
            raise DirecteriorError("rm --purge is permanently deleted and cannot be undone")
        leaf = _path(record, "leaf")
        target = _path(record, "target")
        local_trash = _path(record, "local_trash")
        hdd_trash = _path(record, "hdd_trash")
        local_snapshot = _named_snapshot(record, "local_snapshot")
        hdd_existed = record.details.get("hdd_existed") is True
        if not _absent(leaf) or not _matches_tree_no_follow(
            local_trash, local_snapshot
        ):
            raise DirecteriorError(f"changed since rm: {local_trash}")
        if hdd_existed:
            hdd_snapshot = _named_snapshot(record, "hdd_snapshot")
            if not _absent(target) or not _matches_tree(hdd_trash, hdd_snapshot):
                raise DirecteriorError(f"changed since rm: {hdd_trash}")
            _move_verified(hdd_trash, target, True, "undo rm")
        _move_verified(local_trash, leaf, True, "undo rm")
        if record.details.get("offloaded") is True:
            results = _path(record, "results")
            if not _absent(results):
                raise DirecteriorError(f"restore target already exists: {results}")
            make_link(results, target)
        trash_operation = hdd_trash.parent
        for directory in (
            local_trash.parent,
            trash_operation,
            trash_operation.parent,
        ):
            with suppress(OSError):
                directory.rmdir()
    else:
        raise DirecteriorError(f"undo is unsupported for {record.operation_type}")

    undone = _save(record, "undone")
    print(f"undone {record.operation_type} {record.operation_id}")
    return undone


def interrupted_records(root: Path) -> list[OperationRecord | MigrationRecord]:
    """Journals that `recover` can still resume, newest first."""
    records: list[OperationRecord | MigrationRecord] = [
        *(
            record
            for record in list_operation_records(root)
            if record.state not in {"committed", "undone", "purge_started"}
        ),
        *(record for record in list_records(root) if record.state == "prepared"),
    ]
    return sorted(records, key=lambda item: item.created_at, reverse=True)


def recover_operation(
    root: Path, operation_id: str, approved: bool
) -> OperationRecord | MigrationRecord:
    if not approved:
        raise DirecteriorError(
            "recover may delete a verified source; pass --yes only AFTER explicit approval"
        )
    record: OperationRecord | MigrationRecord
    if operation_id == "latest":
        candidates = interrupted_records(root)
        if not candidates:
            raise DirecteriorError("no interrupted operation to recover")
        record = candidates[0]
    else:
        operations = list_operation_records(root)
        migrations = list_records(root)
        matches = [
            *(record for record in operations if record.operation_id == operation_id),
            *(record for record in migrations if record.operation_id == operation_id),
        ]
        if not matches:
            raise DirecteriorError(f"operation history not found: {operation_id}")
        record = matches[0]
    if Path(record.project_root).resolve() != root.resolve():
        raise DirecteriorError("operation journal belongs to another project")
    if isinstance(record, MigrationRecord):
        if record.state != "prepared":
            raise DirecteriorError(f"cannot recover migration in state: {record.state}")
        from directerior_migrate import continue_migration

        return continue_migration(root, record)
    if record.state in {"committed", "undone"}:
        raise DirecteriorError(f"cannot recover an operation in state: {record.state}")
    if record.state == "purge_started":
        raise DirecteriorError("rm --purge is intentionally non-recoverable")
    return _continue_operation(record)
