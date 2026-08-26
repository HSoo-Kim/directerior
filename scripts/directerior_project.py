from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from directerior_core import (
    CONFIG_NAME,
    NUMBERED_SECTIONS,
    Config,
    DirecteriorError,
    Leaf,
    find_root,
    iter_leaves,
    leaf_relative,
    load_config,
    parse_names,
    require_leaf,
    scaffold_plan,
    section_path,
    write_manifest,
)
from directerior_guards import (
    require_clean_worktree,
    require_new_project,
    require_no_agent_assets,
    require_no_breaking_references,
)
from directerior_ops import PathMove, new_record, save_operation, structure_digest
from directerior_storage import directory_size, is_offloaded


def initialize(
    hdd_root: str,
    threshold_mb: int,
    hierarchy_raw: str,
    allow_existing: bool = False,
) -> None:
    root = Path.cwd().resolve()
    config_path = root / CONFIG_NAME
    if config_path.exists():
        raise DirecteriorError(f"{config_path} already exists")
    hierarchy = tuple(part.strip() for part in hierarchy_raw.split(",") if part.strip())
    if not hierarchy:
        raise DirecteriorError("--hierarchy needs at least one level name")
    source_files = require_new_project(root, allow_existing)
    raw = {
        "hdd_root": hdd_root,
        "threshold_mb": threshold_mb,
        "hierarchy": list(hierarchy),
        "sections": NUMBERED_SECTIONS,
    }
    config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    (root / hierarchy[0]).mkdir(exist_ok=True)
    print(f"initialized {config_path}")
    print(json.dumps(raw, indent=2))
    if source_files:
        print(
            f"NOTE: {source_files} pre-existing source file(s) stay unmanaged. "
            "directerior moves directories but never rewrites imports or hardcoded paths."
        )


def create_experiment(names_raw: list[str], description: str) -> None:
    root = find_root()
    config = load_config(root)
    names = parse_names(config, names_raw)
    path = root / leaf_relative(config, names)
    if path.exists():
        raise DirecteriorError(f"already exists: {path}")
    leaf = Leaf(names=names, path=path)
    scaffold_plan(section_path(leaf, config, "plan"))
    section_path(leaf, config, "code").mkdir()
    section_path(leaf, config, "results").mkdir()
    write_manifest(leaf, config, description, date.today().isoformat())
    print(f"created {path.relative_to(root)}")


def scan_entries(root: Path, config: Config) -> list[dict[str, str | int | list[str]]]:
    threshold = config.threshold_mb * 1024 * 1024
    entries: list[dict[str, str | int | list[str]]] = []
    for leaf in iter_leaves(root, config):
        results = section_path(leaf, config, "results")
        if not results.exists() or is_offloaded(results):
            continue
        size = directory_size(results)
        if size > threshold:
            entries.append({"names": list(leaf.names), "label": leaf.label, "bytes": size})
    return entries


def status_entries(root: Path, config: Config) -> list[dict[str, str | int | list[str]]]:
    threshold = config.threshold_mb * 1024 * 1024
    entries: list[dict[str, str | int | list[str]]] = []
    for leaf in iter_leaves(root, config):
        results = section_path(leaf, config, "results")
        if results.exists() and is_offloaded(results):
            location = "hdd"
            size = 0
        else:
            size = directory_size(results) if results.exists() else 0
            location = "local_over_threshold" if size > threshold else "local"
        entries.append(
            {
                "names": list(leaf.names),
                "label": leaf.label,
                "location": location,
                "bytes": size,
            }
        )
    return entries


def adopt_output(
    source_raw: str,
    names_raw: list[str],
    destination_name: str,
    link_back: bool,
    approved: bool,
    section: str,
    allow_breaking_refs: bool = False,
    allow_dirty: bool = False,
) -> None:
    if not approved:
        raise DirecteriorError("adopt moves data; pass --yes only AFTER explicit user approval")
    root = find_root()
    config = load_config(root)
    source = Path(source_raw).resolve()
    if not source.exists():
        raise DirecteriorError(f"source not found: {source}")
    if source == root or source in root.parents:
        raise DirecteriorError(f"refusing to adopt the project root or an ancestor: {source}")
    require_no_agent_assets(source, "adopt")
    leaf = require_leaf(root, config, parse_names(config, names_raw))
    destination_root = section_path(leaf, config, section)
    if section == "results" and is_offloaded(destination_root):
        raise DirecteriorError(f"results section is offloaded; restore first: {destination_root}")
    if source == destination_root or destination_root in source.parents:
        raise DirecteriorError(f"already inside managed {section} section: {source}")
    if link_back and not source.is_dir():
        raise DirecteriorError("--link works for directories only")
    destination = destination_root / (destination_name or source.name)
    if destination.exists():
        raise DirecteriorError(f"destination already exists: {destination}")
    if not link_back:
        require_no_breaking_references(
            root,
            source,
            section,
            [config.hdd_root],
            allow_breaking_refs,
        )
    head = require_clean_worktree(root, "adopt", allow_dirty)
    digest = structure_digest(source)
    is_dir = source.is_dir()
    source.rename(destination)
    if link_back:
        from directerior_storage import make_link

        make_link(source, destination)
    record = new_record(
        "adopt",
        root,
        head,
        (
            PathMove(
                source=str(source),
                destination=str(destination),
                is_dir=is_dir,
                digest=digest,
                linked_back=link_back,
            ),
        ),
    )
    save_operation(record)
    print(f"adopted {source} -> {destination.relative_to(root)}")
    if link_back:
        print(f"  linked back: {source} -> {destination}")
    print(f"  operation={record.operation_id}")
    print(f"  undo with: expman.py undo {record.operation_id} --yes")


def _alpha_label(index: int) -> str:
    label = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(ord("a") + remainder) + label
    return label


def add_numbered(parent_raw: str, slug: str, group: int | None, file: bool) -> None:
    root = find_root()
    parent = (root / parent_raw).resolve()
    if parent != root and root not in parent.parents:
        raise DirecteriorError(f"parent must stay inside project: {parent}")
    if not parent.is_dir():
        raise DirecteriorError(f"parent not found: {parent}")
    if "/" in slug or "\\" in slug:
        raise DirecteriorError(f"invalid slug: {slug!r}")
    names = [path.name for path in parent.iterdir()]
    if group is None:
        numbers = [
            int(name.split("_", 1)[0])
            for name in names
            if name.split("_", 1)[0].isdigit()
        ]
        prefix = str(max(numbers, default=0) + 1)
    else:
        marker = f"{group}_"
        variants = sorted(
            name[len(marker) :].split("_", 1)[0]
            for name in names
            if name.startswith(marker) and "_" in name[len(marker) :]
        )
        prefix = f"{group}_{_alpha_label(len(variants) + 1)}"
    target = parent / f"{prefix}_{slug}"
    if file:
        target.touch(exist_ok=False)
    else:
        target.mkdir()
    print(target.relative_to(root))
