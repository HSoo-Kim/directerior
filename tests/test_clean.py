from __future__ import annotations

import json
import shutil
from pathlib import Path

from conftest import run_cli
from directerior_storage import is_offloaded, link_target, make_link


def _paths(root: Path) -> tuple[Path, Path]:
    results = root / "methods" / "lora" / "experiments" / "exp01" / "3_results"
    hdd_root = Path(json.loads((root / ".expman.json").read_text())["hdd_root"])
    target = hdd_root / root.name / "methods" / "lora" / "experiments" / "exp01" / "3_results"
    return results, target


def test_numbered_hdd_orphan_is_reported(numbered_project: Path) -> None:
    hdd_root = Path(json.loads((numbered_project / ".expman.json").read_text())["hdd_root"])
    orphan = (
        hdd_root
        / numbered_project.name
        / "methods"
        / "ghost"
        / "experiments"
        / "exp99"
        / "3_results"
    )
    orphan.mkdir(parents=True)
    (orphan / "data.bin").write_bytes(b"orphan")

    result = run_cli(numbered_project, "clean")

    assert result.returncode == 2
    assert f"ORPHAN ON HDD: {orphan}" in result.stdout


def test_clean_fix_repairs_wrong_link(numbered_project: Path, tmp_path: Path) -> None:
    results, target = _paths(numbered_project)
    shutil.rmtree(results)
    target.mkdir(parents=True)
    (target / "data.bin").write_bytes(b"expected")
    wrong = tmp_path / "wrong-target"
    wrong.mkdir()
    make_link(results, wrong)

    result = run_cli(numbered_project, "clean", "--fix")

    assert result.returncode == 0
    assert link_target(results) == target.resolve()
    assert (target / "data.bin").read_bytes() == b"expected"
    assert wrong.is_dir()


def test_clean_fix_does_not_mutate_link_when_target_missing(numbered_project: Path) -> None:
    results, target = _paths(numbered_project)
    shutil.rmtree(results)
    target.mkdir(parents=True)
    make_link(results, target)
    shutil.rmtree(target)

    result = run_cli(numbered_project, "clean", "--fix")

    assert result.returncode == 2
    assert f"BROKEN LINK: lora/exp01; expected target missing: {target}" in result.stdout
    assert is_offloaded(results)
    assert not target.exists()


def test_clean_fix_reports_regular_directory_conflict(numbered_project: Path) -> None:
    results, target = _paths(numbered_project)
    (results / "local.bin").write_bytes(b"local")
    target.mkdir(parents=True)
    (target / "remote.bin").write_bytes(b"remote")

    result = run_cli(numbered_project, "clean", "--fix")

    assert result.returncode == 2
    assert f"regular path blocks link repair: {results}" in result.stdout
    assert f"ORPHAN ON HDD: {target}" in result.stdout
    assert (results / "local.bin").read_bytes() == b"local"
    assert (target / "remote.bin").read_bytes() == b"remote"


def test_clean_keeps_empty_directories_inside_offloaded_results(
    numbered_project: Path,
) -> None:
    results, target = _paths(numbered_project)
    (results / "checkpoints").mkdir()
    (results / "log.txt").write_text("x", encoding="utf-8")
    assert run_cli(numbered_project, "offload", "lora", "exp01", "--yes").returncode == 0
    (target / "log.txt").unlink()
    stale_container = target.parents[1] / "exp-stale"
    stale_container.mkdir()

    result = run_cli(numbered_project, "clean")

    assert result.returncode == 0
    assert (target / "checkpoints").is_dir()
    assert link_target(results) == target.resolve()
    assert not stale_container.exists()


def test_clean_preserves_and_reports_trash(numbered_project: Path) -> None:
    _results, target = _paths(numbered_project)
    operation = target.parents[5] / ".trash" / numbered_project.name / "op-123"
    operation.mkdir(parents=True)
    (operation / "artifact.bin").write_bytes(b"trash")

    result = run_cli(numbered_project, "clean")

    assert result.returncode == 0
    assert f"TRASH: {operation}" in result.stdout
    assert (operation / "artifact.bin").read_bytes() == b"trash"
