from __future__ import annotations

from pathlib import Path

from conftest import run_cli


def test_add_uses_next_numeric_prefix_by_default(project: Path) -> None:
    # Given
    parent = project / "notes"
    parent.mkdir()

    # When
    first = run_cli(project, "add", "notes", "objective.md", "--file")
    second = run_cli(project, "add", "notes", "protocol.md", "--file")

    # Then
    assert first.returncode == 0
    assert second.returncode == 0
    assert (parent / "1_objective.md").is_file()
    assert (parent / "2_protocol.md").is_file()


def test_add_uses_alpha_suffix_for_parallel_group(project: Path) -> None:
    # Given
    parent = project / "variants"
    parent.mkdir()

    # When
    first = run_cli(project, "add", "variants", "baseline", "--group", "1")
    second = run_cli(project, "add", "variants", "ablation", "--group", "1")

    # Then
    assert first.returncode == 0
    assert second.returncode == 0
    assert (parent / "1_a_baseline").is_dir()
    assert (parent / "1_b_ablation").is_dir()
