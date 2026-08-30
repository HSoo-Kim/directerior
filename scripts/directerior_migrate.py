from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from directerior_core import (
    CONFIG_NAME,
    NUMBERED_SECTIONS,
    PLAN_TEMPLATES,
    Config,
    DirecteriorError,
    Leaf,
    find_root,
    hdd_results_path,
    iter_leaves,
    load_config,
    scaffold_plan,
    section_path,
)
from directerior_guards import require_approval, require_clean_worktree
from directerior_history import (
    LeafMigration,
    MigrationRecord,
    compute_fingerprint,
    find_parent_id,
    list_records,
    load_record,
    new_operation_id,
    save_record,
)
from directerior_storage import (
    TreeSnapshot,
    is_offloaded,
    link_target,
    make_link,
    remove_link,
    require_plain_tree,
    tree_snapshot,
)

EMPTY_SNAPSHOT = TreeSnapshot(
    file_count=0,
    byte_count=0,
    digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
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

def _numbered_config_bytes(before: bytes) -> bytes:
    raw = json.loads(before.decode("utf-8"))
    raw["sections"] = NUMBERED_SECTIONS
    return (json.dumps(raw, indent=2) + "\n").encode()


def _preflight(config: Config) -> list[Leaf]:
    leaves = list(iter_leaves(find_root(), config))
    for leaf in leaves:
        for destination in NUMBERED_SECTIONS.values():
            if (leaf.path / destination).exists():
                raise DirecteriorError(
                    f"migration destination already exists: {leaf.path / destination}"
                )
    return leaves


def _build_record(root: Path, config: Config, leaves: list[Leaf]) -> MigrationRecord:
    before = (root / CONFIG_NAME).read_bytes()
    new_config = replace(config, sections=dict(NUMBERED_SECTIONS))
    records: list[LeafMigration] = []
    for leaf in leaves:
        code = section_path(leaf, config, "code")
        results = section_path(leaf, config, "results")
        offloaded = is_offloaded(results)
        old_target = hdd_results_path(config, root, leaf.names) if offloaded else Path()
        new_target = hdd_results_path(new_config, root, leaf.names) if offloaded else Path()
        code_existed = code.is_dir()
        results_existed = results.is_dir() or offloaded
        if code_existed:
            require_plain_tree(code, "migrate-layout")
        if results_existed:
            require_plain_tree(
                old_target if offloaded else results,
                "migrate-layout",
            )
        records.append(
            LeafMigration(
                names=leaf.names,
                leaf_relative=str(leaf.path.relative_to(root)),
                code_existed=code_existed,
                results_existed=results_existed,
                offloaded=offloaded,
                code_snapshot=tree_snapshot(code) if code_existed else EMPTY_SNAPSHOT,
                results_snapshot=(
                    tree_snapshot(old_target)
                    if offloaded
                    else tree_snapshot(results)
                    if results_existed
                    else EMPTY_SNAPSHOT
                ),
                plan_snapshot=None,
                old_hdd_target=str(old_target),
                new_hdd_target=str(new_target),
            )
        )
    record = MigrationRecord(
        operation_id=new_operation_id(),
        state="prepared",
        project_root=str(root),
        created_at=datetime.now(timezone.utc).isoformat(),
        before_config=before,
        after_config=_numbered_config_bytes(before),
        leaves=tuple(records),
        git_head=_git_head(root),
    )
    before_fingerprint = compute_fingerprint(record, "before")
    return replace(
        record,
        parent_id=find_parent_id(list_records(root), before_fingerprint),
        before_fingerprint=before_fingerprint,
    )


def _paths(root: Path, leaf: LeafMigration) -> tuple[Path, Path, Path, Path, Path, Path]:
    base = root / leaf.leaf_relative
    return (
        base / "code",
        base / "results",
        base / NUMBERED_SECTIONS["plan"],
        base / NUMBERED_SECTIONS["code"],
        base / NUMBERED_SECTIONS["results"],
        base,
    )


def _matches(path: Path, expected: TreeSnapshot) -> bool:
    return path.is_dir() and tree_snapshot(path) == expected


def _plan_complete(path: Path) -> bool:
    if not path.is_dir():
        return False
    entries = list(path.iterdir())
    if {entry.name for entry in entries} != set(PLAN_TEMPLATES):
        return False
    return all(
        entry.is_file()
        and entry.read_text(encoding="utf-8") == PLAN_TEMPLATES[entry.name]
        for entry in entries
    )


def _replace_leaf(
    record: MigrationRecord, index: int, leaf: LeafMigration
) -> MigrationRecord:
    leaves = list(record.leaves)
    leaves[index] = leaf
    return replace(record, leaves=tuple(leaves))


def _save_progress(record: MigrationRecord, **changes: object) -> MigrationRecord:
    updated = replace(record, **changes)
    save_record(updated)
    return updated


def _migration_conflict(
    record: MigrationRecord, leaf: LeafMigration | None, *paths: Path
) -> DirecteriorError:
    label = "/".join(leaf.names) if leaf is not None else "config"
    return DirecteriorError(
        f"migration recovery conflict at {label} ({record.leaf_state}): "
        + ", ".join(str(path) for path in paths)
    )


def continue_migration(root: Path, record: MigrationRecord) -> MigrationRecord:
    if record.state != "prepared":
        raise DirecteriorError(f"cannot recover migration in state: {record.state}")
    while record.next_leaf_index < len(record.leaves):
        index = record.next_leaf_index
        leaf = record.leaves[index]
        old_code, old_results, plan, new_code, new_results, _base = _paths(root, leaf)

        if record.leaf_state == "prepared":
            if not plan.exists():
                scaffold_plan(plan)
            if not _plan_complete(plan):
                raise _migration_conflict(record, leaf, plan)
            leaf = replace(leaf, plan_snapshot=tree_snapshot(plan))
            record = _replace_leaf(record, index, leaf)
            record = _save_progress(record, leaf_state="plan_created")
        elif record.leaf_state == "plan_created":
            before_ready = (
                leaf.code_existed
                and _matches(old_code, leaf.code_snapshot)
                and not new_code.exists()
                or not leaf.code_existed
                and not old_code.exists()
                and not new_code.exists()
            )
            after_ready = (
                not old_code.exists() and _matches(new_code, leaf.code_snapshot)
            )
            if before_ready:
                old_code.rename(new_code) if leaf.code_existed else new_code.mkdir()
            elif not after_ready:
                raise _migration_conflict(record, leaf, old_code, new_code)
            record = _save_progress(record, leaf_state="code_renamed")
        elif record.leaf_state == "code_renamed":
            if leaf.offloaded:
                old_target = Path(leaf.old_hdd_target)
                new_target = Path(leaf.new_hdd_target)
                if link_target(old_results) == old_target.resolve(strict=False):
                    remove_link(old_results)
                elif not (not old_results.exists() and not is_offloaded(old_results)):
                    raise _migration_conflict(record, leaf, old_results)
                if _matches(old_target, leaf.results_snapshot) and not new_target.exists():
                    new_target.parent.mkdir(parents=True, exist_ok=True)
                    old_target.rename(new_target)
                elif not (
                    not old_target.exists()
                    and _matches(new_target, leaf.results_snapshot)
                ):
                    raise _migration_conflict(record, leaf, old_target, new_target)
            else:
                before_ready = (
                    leaf.results_existed
                    and _matches(old_results, leaf.results_snapshot)
                    and not new_results.exists()
                    or not leaf.results_existed
                    and not old_results.exists()
                    and not new_results.exists()
                )
                after_ready = (
                    not old_results.exists()
                    and _matches(new_results, leaf.results_snapshot)
                )
                if before_ready:
                    (
                        old_results.rename(new_results)
                        if leaf.results_existed
                        else new_results.mkdir()
                    )
                elif not after_ready:
                    raise _migration_conflict(record, leaf, old_results, new_results)
            record = _save_progress(record, leaf_state="results_renamed")
        elif record.leaf_state == "results_renamed":
            if leaf.offloaded:
                new_target = Path(leaf.new_hdd_target)
                if not _matches(new_target, leaf.results_snapshot):
                    raise _migration_conflict(record, leaf, new_target)
                if not new_results.exists() and not is_offloaded(new_results):
                    make_link(new_results, new_target)
                elif link_target(new_results) != new_target.resolve(strict=False):
                    raise _migration_conflict(record, leaf, new_results, new_target)
            record = _save_progress(record, leaf_state="linked")
        elif record.leaf_state == "linked":
            if leaf.plan_snapshot is None or not _matches(plan, leaf.plan_snapshot):
                raise _migration_conflict(record, leaf, plan)
            if not _matches(new_code, leaf.code_snapshot):
                raise _migration_conflict(record, leaf, new_code)
            result_data = Path(leaf.new_hdd_target) if leaf.offloaded else new_results
            if not _matches(result_data, leaf.results_snapshot):
                raise _migration_conflict(record, leaf, result_data)
            if leaf.offloaded and link_target(new_results) != result_data.resolve(
                strict=False
            ):
                raise _migration_conflict(record, leaf, new_results)
            record = _save_progress(
                record,
                next_leaf_index=index + 1,
                leaf_state="prepared",
            )
        else:
            raise _migration_conflict(record, leaf)

    config_path = root / CONFIG_NAME
    if record.leaf_state == "prepared":
        current = config_path.read_bytes()
        if current == record.before_config:
            staging = config_path.with_name(f"{CONFIG_NAME}.{record.operation_id}.tmp")
            staging.write_bytes(record.after_config)
            staging.replace(config_path)
        elif current != record.after_config:
            raise _migration_conflict(record, None, config_path)
        record = _save_progress(record, leaf_state="config_replaced")
    if record.leaf_state != "config_replaced":
        raise _migration_conflict(record, None, config_path)
    committed = replace(
        record,
        state="committed",
        after_fingerprint=compute_fingerprint(record, "after"),
    )
    _verify_applied(root, committed)
    save_record(committed)
    return committed


def _verify_applied(root: Path, record: MigrationRecord) -> None:
    if (root / CONFIG_NAME).read_bytes() != record.after_config:
        raise DirecteriorError("project config changed since migration")
    for leaf in record.leaves:
        old_code, old_results, plan, new_code, new_results, _base = _paths(root, leaf)
        result_data = Path(leaf.new_hdd_target) if leaf.offloaded else new_results
        plan_matches = leaf.plan_snapshot is not None and _matches(plan, leaf.plan_snapshot)
        link_matches = not leaf.offloaded or is_offloaded(new_results)
        if (
            old_code.exists()
            or old_results.exists()
            or not _matches(new_code, leaf.code_snapshot)
            or not _matches(result_data, leaf.results_snapshot)
            or not plan_matches
            or not link_matches
        ):
            raise DirecteriorError(f"changed since migration: {'/'.join(leaf.names)}")


def _verify_undone(root: Path, record: MigrationRecord) -> None:
    if (root / CONFIG_NAME).read_bytes() != record.before_config:
        raise DirecteriorError("project config changed since undo")
    for leaf in record.leaves:
        old_code, old_results, plan, new_code, new_results, _base = _paths(root, leaf)
        result_data = Path(leaf.old_hdd_target) if leaf.offloaded else old_results
        code_matches = (
            _matches(old_code, leaf.code_snapshot)
            if leaf.code_existed
            else not old_code.exists()
        )
        result_matches = (
            _matches(result_data, leaf.results_snapshot)
            if leaf.results_existed
            else not old_results.exists()
        )
        link_matches = not leaf.offloaded or is_offloaded(old_results)
        if (
            plan.exists()
            or new_code.exists()
            or new_results.exists()
            or not code_matches
            or not result_matches
            or not link_matches
        ):
            raise DirecteriorError(f"changed since undo: {'/'.join(leaf.names)}")


def migrate_layout(approved: bool, dry_run: bool = False, allow_dirty: bool = False) -> None:
    root = find_root()
    config = load_config(root)
    if config.sections == NUMBERED_SECTIONS:
        raise DirecteriorError("project already uses numbered sections")
    leaves = _preflight(config)
    if dry_run:
        for leaf in leaves:
            print(f"{leaf.path}: code/results -> 1_plan/2_code/3_results")
        return
    require_approval(approved, "migrate-layout")
    require_clean_worktree(root, "migrate-layout", allow_dirty)
    record = _build_record(root, config, leaves)
    save_record(record)
    committed = continue_migration(root, record)
    print(f"migrated {root}; operation={committed.operation_id}")
    print(f"  undo: directerior undo {committed.operation_id} --yes")


def undo_migration(operation_id: str, approved: bool) -> None:
    require_approval(approved, "undo")
    root = find_root()
    record = load_record(root, operation_id)
    if record.state != "committed":
        raise DirecteriorError(f"cannot undo migration in state: {record.state}")
    _verify_applied(root, record)
    for leaf in reversed(record.leaves):
        old_code, old_results, plan, new_code, new_results, _base = _paths(root, leaf)
        shutil.rmtree(plan)
        if leaf.code_existed:
            new_code.rename(old_code)
        else:
            new_code.rmdir()
        if leaf.offloaded:
            old_target = Path(leaf.old_hdd_target)
            new_target = Path(leaf.new_hdd_target)
            remove_link(new_results)
            old_target.parent.mkdir(parents=True, exist_ok=True)
            new_target.rename(old_target)
            make_link(old_results, old_target)
        elif leaf.results_existed:
            new_results.rename(old_results)
        else:
            new_results.rmdir()
    (root / CONFIG_NAME).write_bytes(record.before_config)
    undone = replace(record, state="undone")
    _verify_undone(root, undone)
    save_record(undone)
    print(f"undone migration {record.operation_id}")


def redo_migration(operation_id: str, approved: bool) -> None:
    require_approval(approved, "redo")
    root = find_root()
    record = load_record(root, operation_id)
    if record.state != "undone":
        raise DirecteriorError(f"cannot redo migration in state: {record.state}")
    _verify_undone(root, record)
    committed = continue_migration(
        root,
        replace(
            record,
            state="prepared",
            next_leaf_index=0,
            leaf_state="prepared",
            after_fingerprint="",
        ),
    )
    print(f"redone migration {committed.operation_id}")
