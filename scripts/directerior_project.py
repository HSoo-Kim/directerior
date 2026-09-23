from __future__ import annotations

import json
import re
import uuid
from datetime import date
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
    leaf_relative,
    load_config,
    parse_names,
    require_inside_root,
    require_leaf,
    scaffold_plan,
    section_path,
    validate_component,
    validate_config,
    write_manifest,
)
from directerior_guards import (
    require_clean_worktree,
    require_new_project,
    require_no_agent_assets,
    require_no_breaking_references,
)
from directerior_ops import interrupted_records, start_adopt
from directerior_storage import (
    directory_size,
    is_offloaded,
    link_target,
    require_plain_tree,
    tree_snapshot,
)


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
    hierarchy = [part.strip() for part in hierarchy_raw.split(",")]
    source_files = require_new_project(root, allow_existing)
    raw = {
        "schema": 2,
        "project_id": uuid.uuid4().hex[:12],
        "hdd_root": hdd_root,
        "threshold_mb": threshold_mb,
        "hierarchy": hierarchy,
        "sections": NUMBERED_SECTIONS,
    }
    config = validate_config(raw, root)
    config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    (root / config.hierarchy[0]).mkdir(exist_ok=True)
    print(f"initialized {config_path}")
    print(json.dumps(raw, indent=2))
    if source_files:
        print(
            f"NOTE: {source_files} pre-existing source file(s) stay unmanaged. "
            "directerior moves directories but never rewrites imports or hardcoded paths."
        )


def upgrade_config(approved: bool, allow_dirty: bool) -> None:
    if not approved:
        raise DirecteriorError(
            "upgrade-config rewrites project identity; pass --yes only AFTER explicit approval"
        )
    root = find_root()
    config = load_config(root)
    if config.schema == 2:
        raise DirecteriorError("config already uses schema 2")
    if any(not value for value in config.sections.values()):
        raise DirecteriorError("run migrate-layout --yes before upgrade-config")
    if any(
        is_offloaded(section_path(leaf, config, "results"))
        for leaf in iter_leaves(root, config)
    ):
        raise DirecteriorError(
            "upgrade-config refuses while results are offloaded; restore offloaded leaves first"
        )
    # Interrupted journals record paths in the current HDD namespace.
    pending = [record.operation_id for record in interrupted_records(root)]
    if pending:
        raise DirecteriorError(
            "upgrade-config refuses while operations are interrupted; "
            f"run 'directerior recover <id> --yes' first: {', '.join(pending)}"
        )
    require_clean_worktree(root, "upgrade-config", allow_dirty)
    raw = json.loads((root / CONFIG_NAME).read_text(encoding="utf-8"))
    raw.update(
        {
            "schema": 2,
            "project_id": uuid.uuid4().hex[:12],
            "sections": config.sections,
        }
    )
    validate_config(raw, root)
    temporary = root / f"{CONFIG_NAME}.tmp"
    try:
        temporary.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / CONFIG_NAME)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"upgraded {root / CONFIG_NAME} to schema 2")


def create_experiment(names_raw: list[str], description: str) -> None:
    root = find_root()
    config = load_config(root)
    names = parse_names(config, names_raw)
    path = root / leaf_relative(config, names)
    if path.exists():
        raise DirecteriorError(f"already exists: {path}")
    require_inside_root(root, path)
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


def status_entries(
    root: Path, config: Config, verify: bool = False
) -> list[dict[str, object]]:
    threshold = config.threshold_mb * 1024 * 1024
    entries: list[dict[str, object]] = []
    for leaf in iter_leaves(root, config):
        results = section_path(leaf, config, "results")
        if is_offloaded(results):
            location = "hdd"
            local_size = 0
            selected = hdd_results_path(config, root, leaf.names)
            stored_size = directory_size(selected) if selected.is_dir() else 0
        else:
            selected = results
            local_size = directory_size(results) if results.exists() else 0
            stored_size = local_size
            location = "local_over_threshold" if local_size > threshold else "local"
        entry: dict[str, object] = {
            "names": list(leaf.names),
            "label": leaf.label,
            "location": location,
            "bytes": local_size,
            "local_bytes": local_size,
            "stored_bytes": stored_size,
            "verified": None,
        }
        if verify:
            if not selected.is_dir():
                raise DirecteriorError(f"status --verify path is missing: {selected}")
            if location == "hdd" and link_target(results) != selected.resolve(strict=False):
                raise DirecteriorError(
                    f"status --verify: {results} does not link to expected target {selected}"
                )
            require_plain_tree(selected, "status --verify")
            snapshot = tree_snapshot(selected)
            entry["verified"] = True
            entry["digest"] = snapshot.digest
        entries.append(entry)
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
    leaf = require_leaf(root, config, parse_names(config, names_raw))
    destination_root = section_path(leaf, config, section)
    if section == "results" and is_offloaded(destination_root):
        raise DirecteriorError(f"results section is offloaded; restore first: {destination_root}")
    if source == destination_root or destination_root in source.parents:
        raise DirecteriorError(f"already inside managed {section} section: {source}")
    require_no_agent_assets(source, "adopt")
    if link_back and not source.is_dir():
        raise DirecteriorError("--link works for directories only")
    if destination_name:
        validate_component(destination_name, "--as")
    destination = destination_root / (destination_name or source.name)
    if destination.exists() or is_offloaded(destination):
        raise DirecteriorError(f"destination already exists: {destination}")
    if not link_back:
        require_no_breaking_references(
            root,
            source,
            section,
            [config.hdd_root],
            allow_breaking_refs,
        )
    require_clean_worktree(root, "adopt", allow_dirty)
    record = start_adopt(root, source, destination, link_back)
    print(
        f"adopted {source} -> {destination.relative_to(root)}; "
        f"operation={record.operation_id}"
    )
    if link_back:
        print(f"  linked back: {source} -> {destination}")


def _alpha_label(index: int) -> str:
    label = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(ord("a") + remainder) + label
    return label


def _alpha_index(label: str) -> int:
    index = 0
    for char in label:
        index = index * 26 + ord(char) - ord("a") + 1
    return index


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
        # Variant labels are the generated a..z, aa..zz; anything longer is a slug.
        variant = re.compile(rf"{group}_([a-z]{{1,2}})_")
        used = [
            _alpha_index(match.group(1))
            for name in names
            if (match := variant.match(name)) is not None
        ]
        prefix = f"{group}_{_alpha_label(max(used, default=0) + 1)}"
    target = parent / f"{prefix}_{slug}"
    if file:
        target.touch(exist_ok=False)
    else:
        target.mkdir()
    print(target.relative_to(root))
