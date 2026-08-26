from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli


def test_rm_requires_explicit_approval(project: Path) -> None:
    # Given
    leaf = project / "methods" / "lora" / "experiments" / "exp01"

    # When
    completed = run_cli(project, "rm", "lora", "exp01")

    # Then
    assert completed.returncode == 1
    assert leaf.is_dir()


def test_rm_deletes_local_experiment_after_approval(project: Path) -> None:
    # Given
    leaf = project / "methods" / "lora" / "experiments" / "exp01"

    # When
    completed = run_cli(project, "rm", "lora", "exp01", "--yes")

    # Then
    assert completed.returncode == 0
    assert not leaf.exists()


def test_rm_deletes_hdd_copy_after_approval(project: Path) -> None:
    # Given
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")
    assert run_cli(project, "offload", "lora", "exp01", "--yes").returncode == 0
    config = json.loads((project / ".expman.json").read_text(encoding="utf-8"))
    hdd_target = (
        Path(config["hdd_root"])
        / project.name
        / "methods"
        / "lora"
        / "experiments"
        / "exp01"
        / "results"
    )

    # When
    completed = run_cli(project, "rm", "lora", "exp01", "--yes")

    # Then
    assert completed.returncode == 0
    assert not hdd_target.exists()
