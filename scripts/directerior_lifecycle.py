from __future__ import annotations

import json
import os
import shutil
import sys
from contextlib import suppress
from pathlib import Path

from directerior_core import (
    DirecteriorError,
    Leaf,
    find_root,
    hdd_results_path,
    iter_leaves,
    leaf_relative,
    load_config,
    parse_names,
    prune_empty_upward,
    require_leaf,
    section_path,
    update_manifest_levels,
)
from directerior_guards import (
    require_approval,
    require_clean_worktree,
    require_no_agent_assets,
)
from directerior_history import new_operation_id
from directerior_ops import (
    PathMove,
    iter_trash,
    new_record,
    save_operation,
    structure_digest,
    trash_root,
)
from directerior_storage import (
    copy_tree_verified,
    is_offloaded,
    make_link,
    remove_link,
    same_volume,
)


def offload(names_raw: list[str], approved: bool, allow_dirty: bool = False) -> None:
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
    snapshot = copy_tree_verified(results, target)
    shutil.rmtree(results)
    make_link(results, target)
    print(f"offloaded {'/'.join(names)} ({snapshot.byte_count} bytes)")
    print(f"  moved to: {target}")


def restore(names_raw: list[str], approved: bool, allow_dirty: bool = False) -> None:
    require_approval(approved, "restore")
    root = find_root()
    config = load_config(root)
    require_clean_worktree(root, "restore", allow_dirty)
    names = parse_names(config, names_raw)
    results = section_path(require_leaf(root, config, names), config, "results")
    if not is_offloaded(results):
        raise DirecteriorError(f"not offloaded: {results}")
    source = hdd_results_path(config, root, names)
    staging = results.with_name("results.restore")
    if same_volume(source, staging):
        print("WARNING: source and restore target are on the same volume", file=sys.stderr)
    copy_tree_verified(source, staging)
    remove_link(results)
    staging.rename(results)
    shutil.rmtree(source)
    prune_empty_upward(source.parent, config.hdd_root)
    print(f"restored {'/'.join(names)} -> {results}")


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
    if new_path.exists():
        raise DirecteriorError(f"destination already exists: {new_path}")
    old_results = section_path(old_leaf, config, "results")
    old_target = hdd_results_path(config, root, old_names)
    new_target = hdd_results_path(config, root, new_names)
    offloaded = is_offloaded(old_results)
    if offloaded:
        remove_link(old_results)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_leaf.path.rename(new_path)
    if offloaded:
        new_target.parent.mkdir(parents=True, exist_ok=True)
        old_target.rename(new_target)
        make_link(section_path(Leaf(new_names, new_path), config, "results"), new_target)
        prune_empty_upward(old_target.parent, config.hdd_root)
    new_leaf = Leaf(names=new_names, path=new_path)
    update_manifest_levels(new_leaf, config)
    prune_empty_upward(old_leaf.path.parent, root)
    print(f"renamed {'/'.join(old_names)} -> {'/'.join(new_names)}")


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
    results = section_path(leaf, config, "results")
    target = hdd_results_path(config, root, names)
    head = require_clean_worktree(root, "rm", allow_dirty)
    offloaded = is_offloaded(results)
    if offloaded:
        remove_link(results)
    if purge:
        shutil.rmtree(leaf.path)
        if target.is_dir():
            shutil.rmtree(target)
            prune_empty_upward(target.parent, config.hdd_root)
        prune_empty_upward(leaf.path.parent, root)
        print(f"purged {'/'.join(names)} - permanently deleted, no undo")
        return
    operation_id = new_operation_id()
    trash = trash_root(config.hdd_root, root.name, operation_id)
    trash.mkdir(parents=True)
    moves: list[PathMove] = []
    if target.is_dir():
        hdd_trash = trash / "hdd"
        moves.append(
            PathMove(str(target), str(hdd_trash), True, structure_digest(target), False)
        )
        shutil.move(str(target), str(hdd_trash))
        prune_empty_upward(target.parent, config.hdd_root)
    local_trash = trash / "local"
    moves.append(
        PathMove(str(leaf.path), str(local_trash), True, structure_digest(leaf.path), False)
    )
    if same_volume(leaf.path, trash):
        print("WARNING: trash is on the same volume as the project", file=sys.stderr)
    shutil.move(str(leaf.path), str(local_trash))
    prune_empty_upward(leaf.path.parent, root)
    record = new_record(
        "rm",
        root,
        head,
        tuple(moves),
        (str(results), str(target)) if offloaded else None,
        operation_id=operation_id,
    )
    save_operation(record)
    print(f"removed {'/'.join(names)} -> trash: {trash}")
    print(f"  operation={operation_id} (undo with: expman.py undo {operation_id} --yes)")


def clean(fix: bool) -> int:
    root = find_root()
    config = load_config(root)
    hdd_project = config.hdd_root / root.name
    issues = 0
    for leaf in iter_leaves(root, config):
        results = section_path(leaf, config, "results")
        if not is_offloaded(results):
            continue
        if hdd_results_path(config, root, leaf.names).is_dir():
            continue
        issues += 1
        if fix:
            remove_link(results)
            results.mkdir()
            print(f"fixed broken link: {leaf.label}")
        else:
            print(f"BROKEN LINK: {leaf.label} (use --fix)")
    if hdd_project.is_dir():
        pattern = "/".join(f"{level}/*" for level in config.hierarchy) + "/results"
        for target in sorted(hdd_project.glob(pattern)):
            relative = target.relative_to(hdd_project)
            names = tuple(relative.parts[1::2])
            local_leaf = Leaf(names, root / leaf_relative(config, names))
            local = section_path(local_leaf, config, "results")
            if is_offloaded(local):
                continue
            issues += 1
            print(f"ORPHAN ON HDD: {target}")
        for directory, _subdirs, _files in os.walk(hdd_project, topdown=False):
            with suppress(OSError):
                Path(directory).rmdir()
    for entry in iter_trash(config.hdd_root, root.name):
        print(f"TRASH: {entry} (undo with: expman.py undo {entry.name} --yes)")
    print(json.dumps({"issues": issues}) if fix else f"clean: {issues} issue(s)")
    return 2 if issues and not fix else 0
