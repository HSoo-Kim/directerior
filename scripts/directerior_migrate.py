from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from directerior_core import (
    CONFIG_NAME,
    NUMBERED_SECTIONS,
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
    make_link,
    remove_link,
    tree_snapshot,
)

EMPTY_SNAPSHOT = TreeSnapshot(
    file_count=0,
    byte_count=0,
    digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
)


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


def _apply(root: Path, record: MigrationRecord) -> MigrationRecord:
    updated: list[LeafMigration] = []
    for leaf in record.leaves:
        old_code, old_results, plan, new_code, new_results, _base = _paths(root, leaf)
        scaffold_plan(plan)
        if leaf.code_existed:
            old_code.rename(new_code)
        else:
            new_code.mkdir()
        if leaf.offloaded:
            old_target = Path(leaf.old_hdd_target)
            new_target = Path(leaf.new_hdd_target)
            remove_link(old_results)
            new_target.parent.mkdir(parents=True, exist_ok=True)
            old_target.rename(new_target)
            make_link(new_results, new_target)
        elif leaf.results_existed:
            old_results.rename(new_results)
        else:
            new_results.mkdir()
        updated.append(replace(leaf, plan_snapshot=tree_snapshot(plan)))
    (root / CONFIG_NAME).write_bytes(record.after_config)
    applied_without_fingerprint = replace(record, state="applied", leaves=tuple(updated))
    applied = replace(
        applied_without_fingerprint,
        after_fingerprint=compute_fingerprint(applied_without_fingerprint, "after"),
    )
    _verify_applied(root, applied)
    return applied


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
    applied = _apply(root, record)
    save_record(applied)
    print(f"migrated {root}; operation={applied.operation_id}")


def undo_migration(operation_id: str, approved: bool) -> None:
    require_approval(approved, "undo")
    root = find_root()
    record = load_record(root, operation_id)
    if record.state != "applied":
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
    applied = _apply(root, replace(record, state="prepared"))
    save_record(applied)
    print(f"redone migration {record.operation_id}")
