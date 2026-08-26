from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli


def test_rename_requires_explicit_approval(project: Path) -> None:
    # Given
    old_leaf = project / "methods" / "lora" / "experiments" / "exp01"

    # When
    completed = run_cli(project, "rename", "lora", "exp01", "--to", "lora", "baseline")

    # Then
    assert completed.returncode == 1
    assert old_leaf.is_dir()


def test_rename_moves_local_leaf_and_updates_manifest(project: Path) -> None:
    # Given
    old_leaf = project / "methods" / "lora" / "experiments" / "exp01"
    new_leaf = project / "methods" / "lora" / "experiments" / "baseline"

    # When
    completed = run_cli(
        project,
        "rename",
        "lora",
        "exp01",
        "--to",
        "lora",
        "baseline",
        "--yes",
    )

    # Then
    assert completed.returncode == 0
    assert not old_leaf.exists()
    assert new_leaf.is_dir()
    manifest = json.loads((new_leaf / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["levels"] == {"methods": "lora", "experiments": "baseline"}


def test_rename_moves_hdd_target_and_rebuilds_link(project: Path) -> None:
    # Given
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")
    assert run_cli(project, "offload", "lora", "exp01", "--yes").returncode == 0
    config = json.loads((project / ".expman.json").read_text(encoding="utf-8"))
    old_target = (
        Path(config["hdd_root"])
        / project.name
        / "methods"
        / "lora"
        / "experiments"
        / "exp01"
        / "results"
    )
    new_target = old_target.parents[1] / "baseline" / "results"

    # When
    completed = run_cli(
        project,
        "rename",
        "lora",
        "exp01",
        "--to",
        "lora",
        "baseline",
        "--yes",
    )

    # Then
    assert completed.returncode == 0
    assert not old_target.exists()
    assert (new_target / "artifact.bin").read_bytes() == b"payload"
    linked_results = project / "methods" / "lora" / "experiments" / "baseline" / "results"
    assert (linked_results / "artifact.bin").read_bytes() == b"payload"
