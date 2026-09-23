from __future__ import annotations

import json
import os
import sys
from contextlib import suppress
from pathlib import Path

from directerior_core import (
    Config,
    DirecteriorError,
    find_root,
    hdd_project_path,
    hdd_results_path,
    iter_leaves,
    leaf_relative,
    load_config,
    parse_names,
    prune_empty_upward,
    require_leaf,
    section_path,
)
from directerior_guards import (
    require_approval,
    require_clean_worktree,
    require_no_agent_assets,
)
from directerior_ops import start_offload, start_remove, start_rename, start_restore
from directerior_storage import (
    is_offloaded,
    link_target,
    make_link,
    remove_link,
    same_volume,
)


def offload(
    names_raw: list[str], approved: bool, allow_dirty: bool = False
) -> None:
    require_approval(approved, "offload")
    root = find_root()
    config = load_config(root)
    require_clean_worktree(root, "offload", allow_dirty)
    names = parse_names(config, names_raw)
    results = section_path(require_leaf(root, config, names), config, "results")
    if is_offloaded(results):
        raise DirecteriorError(f"already offloaded: {results}")
    target = hdd_results_path(config, root, names)
    if same_volume(results, target):
        print("WARNING: source and HDD target are on the same volume", file=sys.stderr)
    record = start_offload(root, config, names, results, target)
    print(f"offloaded {'/'.join(names)}; operation={record.operation_id}")
    print(f"  moved to: {target}")


def restore(
    names_raw: list[str], approved: bool, allow_dirty: bool = False
) -> None:
    require_approval(approved, "restore")
    root = find_root()
    config = load_config(root)
    require_clean_worktree(root, "restore", allow_dirty)
    names = parse_names(config, names_raw)
    results = section_path(require_leaf(root, config, names), config, "results")
    source = hdd_results_path(config, root, names)
    if not is_offloaded(results):
        raise DirecteriorError(f"not offloaded: {results}")
    if same_volume(source, results.parent):
        print("WARNING: source and restore target are on the same volume", file=sys.stderr)
    record = start_restore(root, config, names, results, source)
    print(f"restored {'/'.join(names)} -> {results}; operation={record.operation_id}")


def rename_experiment(
    old_raw: list[str],
    new_raw: list[str],
    approved: bool,
    allow_dirty: bool = False,
) -> None:
    require_approval(approved, "rename")
    root = find_root()
    config = load_config(root)
    require_clean_worktree(root, "rename", allow_dirty)
    old_names = parse_names(config, old_raw)
    new_names = parse_names(config, new_raw)
    old_leaf = require_leaf(root, config, old_names)
    new_path = root / leaf_relative(config, new_names)
    if new_path.exists() or is_offloaded(new_path):
        raise DirecteriorError(f"destination already exists: {new_path}")
    old_results = section_path(old_leaf, config, "results")
    old_target = hdd_results_path(config, root, old_names)
    new_target = hdd_results_path(config, root, new_names)
    record = start_rename(
        root,
        config,
        old_names,
        new_names,
        old_leaf.path,
        new_path,
        old_results,
        old_target,
        new_target,
    )
    prune_empty_upward(old_target.parent, hdd_project_path(config, root))
    prune_empty_upward(old_leaf.path.parent, root)
    print(
        f"renamed {'/'.join(old_names)} -> {'/'.join(new_names)}; "
        f"operation={record.operation_id}"
    )


def remove_experiment(
    names_raw: list[str],
    approved: bool,
    purge: bool = False,
    allow_dirty: bool = False,
) -> None:
    require_approval(approved, "rm")
    root = find_root()
    config = load_config(root)
    names = parse_names(config, names_raw)
    leaf = require_leaf(root, config, names)
    require_no_agent_assets(leaf.path, "rm")
    require_clean_worktree(root, "rm", allow_dirty)
    target = hdd_results_path(config, root, names)
    if not purge and same_volume(leaf.path, hdd_project_path(config, root)):
        print("WARNING: trash is on the same volume as the project", file=sys.stderr)
    record = start_remove(root, config, names, leaf.path, target, purge)
    prune_empty_upward(leaf.path.parent, root)
    action = "purged permanently; no undo" if purge else "removed"
    print(f"{action} {'/'.join(names)}; operation={record.operation_id}")


def _hdd_result_paths(root: Path, config: Config):
    hierarchy = config.hierarchy

    def walk(base: Path, depth: int, names: tuple[str, ...]):
        level = base / hierarchy[depth]
        try:
            entries = sorted(os.scandir(level), key=lambda entry: entry.name)
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            child_names = (*names, entry.name)
            if depth + 1 == len(hierarchy):
                target = hdd_results_path(config, root, child_names)
                if target.is_dir() and not is_offloaded(target):
                    yield child_names, target
            else:
                yield from walk(Path(entry.path), depth + 1, child_names)

    hdd_project = hdd_project_path(config, root)
    if hdd_project.is_dir() and hierarchy:
        yield from walk(hdd_project, 0, ())


def clean(fix: bool) -> int:
    root = find_root()
    config = load_config(root)
    hdd_project = hdd_project_path(config, root)
    repaired = 0
    unresolved = 0
    managed_targets: set[Path] = set()

    for leaf in iter_leaves(root, config):
        results = section_path(leaf, config, "results")
        expected = hdd_results_path(config, root, leaf.names)
        actual = link_target(results)

        if expected.is_dir():
            resolved_expected = expected.resolve(strict=False)
            if actual == resolved_expected:
                managed_targets.add(resolved_expected)
                continue
            if results.exists() and not is_offloaded(results):
                unresolved += 1
                print(f"CONFLICT: {leaf.label}; regular path blocks link repair: {results}")
                continue
            managed_targets.add(resolved_expected)
            if not fix:
                unresolved += 1
                print(f"REPAIRABLE LINK: {leaf.label}; expected target: {expected}")
                continue
            if is_offloaded(results):
                remove_link(results)
            make_link(results, expected)
            repaired += 1
            print(f"repaired link: {leaf.label} -> {expected}")
            continue

        if is_offloaded(results):
            unresolved += 1
            print(f"BROKEN LINK: {leaf.label}; expected target missing: {expected}")

    result_targets: set[Path] = set()
    for _names, target in _hdd_result_paths(root, config):
        result_targets.add(target)
        if target.resolve(strict=False) in managed_targets:
            continue
        unresolved += 1
        print(f"ORPHAN ON HDD: {target}")

    # Prune only the hierarchy scaffolding around result trees. Empty
    # directories inside a results tree are user data and part of its digest.
    if hdd_project.is_dir():
        containers: list[Path] = []
        for directory, subdirs, _files in os.walk(hdd_project):
            base = Path(directory)
            subdirs[:] = [name for name in subdirs if base / name not in result_targets]
            containers.append(base)
        for directory in reversed(containers):
            with suppress(OSError):
                directory.rmdir()

    trash_roots = (
        config.hdd_root / ".trash" / hdd_project.name,
        root / ".directerior-trash",
    )
    seen_trash: set[str] = set()
    for trash_root in trash_roots:
        if not trash_root.is_dir():
            continue
        for entry in sorted(path for path in trash_root.iterdir() if path.is_dir()):
            if entry.name in seen_trash:
                continue
            seen_trash.add(entry.name)
            print(f"TRASH: {entry} (undo with: directerior undo {entry.name} --yes)")

    if fix:
        print(json.dumps({"repaired": repaired, "unresolved": unresolved}))
    else:
        print(f"clean: {unresolved} unresolved issue(s)")
    return 2 if unresolved else 0
