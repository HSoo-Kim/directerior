from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
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
        f"no {CONFIG_NAME} found in {path} or parents; run 'expman.py init' first"
    )


def load_config(root: Path) -> Config:
    raw = json.loads((root / CONFIG_NAME).read_text(encoding="utf-8"))
    hierarchy = tuple(raw.get("hierarchy", DEFAULT_HIERARCHY))
    override = os.environ.get("EXPMAN_HDD_ROOT")
    hdd_root = Path(override if override is not None else raw["hdd_root"])
    return Config(
        hdd_root=hdd_root,
        threshold_mb=int(raw["threshold_mb"]),
        hierarchy=hierarchy,
        sections=dict(raw.get("sections", LEGACY_SECTIONS)),
    )


def parse_names(config: Config, names: list[str]) -> tuple[str, ...]:
    if len(names) != len(config.hierarchy):
        raise DirecteriorError(
            f"hierarchy is {'/'.join(config.hierarchy)}: expected "
            f"{len(config.hierarchy)} name(s), got {len(names)}: {' '.join(names)}"
        )
    for name in names:
        if "/" in name or "\\" in name or name in (".", ".."):
            raise DirecteriorError(f"invalid name: {name!r}")
    return tuple(names)


def leaf_relative(config: Config, names: tuple[str, ...]) -> Path:
    path = Path()
    for container, name in zip(config.hierarchy, names, strict=True):
        path = path / container / name
    return path


def require_leaf(root: Path, config: Config, names: tuple[str, ...]) -> Leaf:
    path = root / leaf_relative(config, names)
    if not path.is_dir():
        raise DirecteriorError(f"not found: {path}")
    return Leaf(names=names, path=path)


def hdd_results_path(config: Config, root: Path, names: tuple[str, ...]) -> Path:
    return (
        config.hdd_root
        / root.name
        / leaf_relative(config, names)
        / config.sections["results"]
    )


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
