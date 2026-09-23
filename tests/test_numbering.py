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


def test_add_group_ignores_plain_numbered_slugs(project: Path) -> None:
    parent = project / "variants"
    parent.mkdir()
    (parent / "1_baseline_v2").mkdir()
    (parent / "1_a_first").mkdir()

    completed = run_cli(project, "add", "variants", "next", "--group", "1")

    assert completed.returncode == 0
    assert (parent / "1_b_next").is_dir()
