from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import ProjectFactory, run_cli
from directerior_core import (
    DirecteriorError,
    hdd_project_path,
    load_config,
    parse_names,
)
from directerior_storage import make_link


def _write(root: Path, raw: object) -> None:
    (root / ".expman.json").write_text(json.dumps(raw), encoding="utf-8")


def _valid(hdd: Path) -> dict[str, object]:
    return {
        "hdd_root": str(hdd),
        "threshold_mb": 100,
        "hierarchy": ["methods", "experiments"],
        "sections": {"plan": "1_plan", "code": "2_code", "results": "3_results"},
    }


def _schema_two_without_sections(raw: dict[str, object]) -> None:
    raw.pop("sections")
    raw.update(schema=2, project_id="0123456789ab")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda raw: raw.update(hdd_root=""), "hdd_root"),
        (lambda raw: raw.update(threshold_mb=0), "positive integer"),
        (lambda raw: raw.update(threshold_mb=-1), "positive integer"),
        (lambda raw: raw.update(hierarchy=[]), "non-empty list"),
        (lambda raw: raw.update(hierarchy=["methods", "methods"]), "unique"),
        (lambda raw: raw.update(hierarchy=["methods", "../escape"]), "path component"),
        (lambda raw: raw.update(hierarchy=["C:escape"]), "path component"),
        (
            lambda raw: raw.update(
                sections={"plan": "1_plan", "code": "2_code", "results": "2_code"}
            ),
            "must be unique",
        ),
        (
            lambda raw: raw.update(
                sections={"plan": "", "code": "2_code", "results": "3_results"}
            ),
            "non-empty path component",
        ),
        (
            lambda raw: raw.update(sections={"code": "2_code", "results": "3_results"}),
            "exactly plan, code, and results",
        ),
        (lambda raw: raw.update(schema=9), "unsupported config schema"),
        (lambda raw: raw.update(schema=2, project_id="BAD"), "project_id"),
        (_schema_two_without_sections, "explicit plan, code, and results sections"),
    ],
)
def test_invalid_config_is_rejected(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    hdd = tmp_path / "hdd"
    raw = _valid(hdd)
    mutate(raw)
    _write(root, raw)

    with pytest.raises(DirecteriorError, match=message):
        load_config(root)


def test_non_object_config_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _write(root, ["not", "an", "object"])

    with pytest.raises(DirecteriorError, match="JSON object"):
        load_config(root)


def test_parse_names_reuses_component_validation(numbered_project: Path) -> None:
    config = load_config(numbered_project)

    with pytest.raises(DirecteriorError, match="non-empty path component"):
        parse_names(config, ["lora", ""])


def test_new_same_named_projects_get_distinct_hdd_namespaces(tmp_path: Path) -> None:
    hdd = tmp_path / "hdd"
    hdd.mkdir()
    first = tmp_path / "one" / "project"
    second = tmp_path / "two" / "project"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    assert run_cli(first, "init", "--hdd-root", str(hdd)).returncode == 0
    assert run_cli(second, "init", "--hdd-root", str(hdd)).returncode == 0

    first_config = load_config(first)
    second_config = load_config(second)
    assert first_config.project_id != second_config.project_id
    assert hdd_project_path(first_config, first) != hdd_project_path(second_config, second)
    assert hdd_project_path(first_config, first).name.startswith("project--")


def test_legacy_config_keeps_basename_archive_path(project: Path) -> None:
    config = load_config(project)

    assert config.schema == 1
    assert config.project_id is None
    assert hdd_project_path(config, project) == config.hdd_root / project.name


def test_upgrade_config_writes_schema_two(numbered_project: Path) -> None:
    result = run_cli(numbered_project, "upgrade-config", "--yes", "--allow-dirty")

    assert result.returncode == 0
    config = load_config(numbered_project)
    assert config.schema == 2
    assert config.project_id is not None
    assert hdd_project_path(config, numbered_project).name == (
        f"{numbered_project.name}--{config.project_id}"
    )


def test_upgrade_refuses_while_results_are_offloaded(
    project_factory: ProjectFactory,
) -> None:
    root = project_factory("numbered", "offloaded-project")
    config = load_config(root)
    results = root / "methods" / "lora" / "experiments" / "exp01" / "3_results"
    target = hdd_project_path(config, root) / results.relative_to(root)
    shutil.rmtree(results)
    target.mkdir(parents=True)
    make_link(results, target)

    result = run_cli(root, "upgrade-config", "--yes", "--allow-dirty")

    assert result.returncode == 1
    assert "restore offloaded leaves first" in result.stderr
    assert load_config(root).schema == 1
