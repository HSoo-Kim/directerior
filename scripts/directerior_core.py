from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Final

CONFIG_NAME: Final = ".expman.json"
DEFAULT_HIERARCHY: Final = ("methods", "experiments")
NUMBERED_SECTIONS: Final = {
    "plan": "1_plan",
    "code": "2_code",
    "results": "3_results",
}
LEGACY_SECTIONS: Final = {
    "plan": "",
    "code": "code",
    "results": "results",
}
PLAN_TEMPLATES: Final = {
    "1_objective.md": "# Objective\n\n",
    "2_hypotheses.md": "# Hypotheses\n\n",
    "3_protocol.md": "# Protocol\n\n",
    "4_decisions.md": "# Decisions\n\n",
}


class DirecteriorError(RuntimeError):
    """Expected user-facing command failure."""


@dataclass(frozen=True, slots=True)
class Config:
    hdd_root: Path
    threshold_mb: int
    hierarchy: tuple[str, ...]
    sections: dict[str, str]
    schema: int
    project_id: str | None


@dataclass(frozen=True, slots=True)
class Leaf:
    names: tuple[str, ...]
    path: Path

    @property
    def label(self) -> str:
        return "/".join(self.names)


def find_root(start: Path | None = None) -> Path:
    path = (start or Path.cwd()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    raise DirecteriorError(
        f"no {CONFIG_NAME} found in {path} or parents; run 'directerior init' first"
    )


def validate_component(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DirecteriorError(f"{field} must be a non-empty path component")
    if (
        value in (".", "..")
        or "/" in value
        or "\\" in value
        or Path(value).is_absolute()
        or bool(PureWindowsPath(value).drive)
    ):
        raise DirecteriorError(f"invalid {field} path component: {value!r}")
    return value


def validate_config(raw: object, root: Path) -> Config:
    if not isinstance(raw, dict):
        raise DirecteriorError(f"{CONFIG_NAME} must contain a JSON object")

    if "schema" not in raw:
        schema = 1
        project_id = None
    elif type(raw["schema"]) is int and raw["schema"] == 2:
        schema = 2
        project_id_raw = raw.get("project_id")
        if not isinstance(project_id_raw, str) or re.fullmatch(
            r"[0-9a-f]{12}", project_id_raw
        ) is None:
            raise DirecteriorError("schema 2 requires a 12-character lowercase hex project_id")
        project_id = project_id_raw
    else:
        raise DirecteriorError(f"unsupported config schema: {raw['schema']!r}")

    hdd_raw = os.environ.get("EXPMAN_HDD_ROOT", raw.get("hdd_root"))
    if not isinstance(hdd_raw, str) or not hdd_raw.strip() or "\x00" in hdd_raw:
        raise DirecteriorError("hdd_root must be a non-empty path string")
    try:
        hdd_root = Path(hdd_raw).expanduser()
    except (OSError, ValueError) as exc:
        raise DirecteriorError(f"invalid hdd_root: {hdd_raw!r}") from exc

    if not hdd_root.is_absolute():
        hdd_root = root / hdd_root
    threshold = raw.get("threshold_mb")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0:
        raise DirecteriorError("threshold_mb must be a positive integer")

    hierarchy_raw = raw.get("hierarchy", list(DEFAULT_HIERARCHY))
    if not isinstance(hierarchy_raw, list) or not hierarchy_raw:
        raise DirecteriorError("hierarchy must be a non-empty list")
    hierarchy = tuple(
        validate_component(value, f"hierarchy[{index}]")
        for index, value in enumerate(hierarchy_raw)
    )
    # Case-insensitive filesystems (Windows, macOS) treat `Part` and `PART` as one name.
    if len({level.casefold() for level in hierarchy}) != len(hierarchy):
        raise DirecteriorError("hierarchy level names must be unique")

    sections_raw = raw.get("sections")
    if sections_raw is None:
        if schema == 2:
            raise DirecteriorError("schema 2 requires explicit plan, code, and results sections")
        sections = dict(LEGACY_SECTIONS)
    else:
        if not isinstance(sections_raw, dict) or set(sections_raw) != {
            "plan",
            "code",
            "results",
        }:
            raise DirecteriorError("sections must define exactly plan, code, and results")
        sections = {
            name: validate_component(sections_raw[name], f"sections.{name}")
            for name in ("plan", "code", "results")
        }
        if len({value.casefold() for value in sections.values()}) != len(sections):
            raise DirecteriorError("section directory names must be unique")

    return Config(
        hdd_root=hdd_root,
        threshold_mb=threshold,
        hierarchy=hierarchy,
        sections=sections,
        schema=schema,
        project_id=project_id,
    )


def load_config(root: Path) -> Config:
    try:
        raw = json.loads((root / CONFIG_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DirecteriorError(f"cannot read valid {CONFIG_NAME}: {exc}") from exc
    return validate_config(raw, root)


def parse_names(config: Config, names: list[str]) -> tuple[str, ...]:
    if len(names) != len(config.hierarchy):
        raise DirecteriorError(
            f"hierarchy is {'/'.join(config.hierarchy)}: expected "
            f"{len(config.hierarchy)} name(s), got {len(names)}: {' '.join(names)}"
        )
    for index, name in enumerate(names):
        validate_component(name, f"name[{index}]")
    return tuple(names)


def leaf_relative(config: Config, names: tuple[str, ...]) -> Path:
    path = Path()
    for container, name in zip(config.hierarchy, names, strict=True):
        path = path / container / name
    return path


def require_inside_root(root: Path, path: Path) -> None:
    """Refuse leaf paths redirected outside the project by a linked container."""
    resolved_root = root.resolve()
    resolved = path.resolve(strict=False)
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise DirecteriorError(f"refusing path that resolves outside the project: {path}")


def require_leaf(root: Path, config: Config, names: tuple[str, ...]) -> Leaf:
    path = root / leaf_relative(config, names)
    if not path.is_dir():
        raise DirecteriorError(f"not found: {path}")
    require_inside_root(root, path)
    return Leaf(names=names, path=path)


def hdd_project_path(config: Config, root: Path) -> Path:
    if config.schema == 2:
        assert config.project_id is not None
        return config.hdd_root / f"{root.name}--{config.project_id}"
    return config.hdd_root / root.name


def hdd_results_path(config: Config, root: Path, names: tuple[str, ...]) -> Path:
    return hdd_project_path(config, root) / leaf_relative(config, names) / config.sections[
        "results"
    ]


def section_path(leaf: Leaf, config: Config, section: str) -> Path:
    directory = config.sections[section]
    return leaf.path if not directory else leaf.path / directory


def iter_leaves(root: Path, config: Config) -> Iterator[Leaf]:
    def walk(base: Path, depth: int, names: tuple[str, ...]) -> Iterator[Leaf]:
        container = base / config.hierarchy[depth]
        if not container.is_dir():
            return
        for child in sorted(path for path in container.iterdir() if path.is_dir()):
            values = (*names, child.name)
            if depth + 1 == len(config.hierarchy):
                yield Leaf(names=values, path=child)
            else:
                yield from walk(child, depth + 1, values)

    yield from walk(root, 0, ())


def write_manifest(leaf: Leaf, config: Config, description: str, created: str) -> None:
    manifest = {
        "levels": dict(zip(config.hierarchy, leaf.names, strict=True)),
        "created": created,
        "description": description,
    }
    (leaf.path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def update_manifest_levels(leaf: Leaf, config: Config) -> None:
    path = leaf.path / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["levels"] = dict(zip(config.hierarchy, leaf.names, strict=True))
    path.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def scaffold_plan(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for filename, content in PLAN_TEMPLATES.items():
        target = path / filename
        if not target.exists():
            target.write_text(content, encoding="utf-8")


def prune_empty_upward(path: Path, stop: Path) -> int:
    removed = 0
    stop_resolved = stop.resolve()
    current = path
    while current.is_dir() and current.resolve() != stop_resolved:
        try:
            current.rmdir()
        except OSError:
            break
        removed += 1
        current = current.parent
    return removed
