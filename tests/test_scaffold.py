from __future__ import annotations

from pathlib import Path

from conftest import run_cli


def test_new_scaffolds_numbered_sections_and_ordered_plan_files(tmp_path: Path) -> None:
    # Given
    root = tmp_path / "new-project"
    root.mkdir()
    hdd = tmp_path / "hdd"
    hdd.mkdir()
    assert (
        run_cli(root, "init", "--hdd-root", str(hdd), "--threshold-mb", "100").returncode
        == 0
    )

    # When
    completed = run_cli(root, "new", "lora", "exp01")

    # Then
    assert completed.returncode == 0
    leaf = root / "methods" / "lora" / "experiments" / "exp01"
    assert (leaf / "1_plan").is_dir()
    assert (leaf / "2_code").is_dir()
    assert (leaf / "3_results").is_dir()
    assert sorted(path.name for path in (leaf / "1_plan").iterdir()) == [
        "1_objective.md",
        "2_hypotheses.md",
        "3_protocol.md",
        "4_decisions.md",
    ]


def test_adopt_maps_existing_path_into_selected_section(tmp_path: Path) -> None:
    # Given
    root = tmp_path / "existing-project"
    root.mkdir()
    hdd = tmp_path / "hdd"
    hdd.mkdir()
    legacy_code = root / "old-scripts"
    legacy_code.mkdir()
    (legacy_code / "train.py").write_text("print('train')\n", encoding="utf-8")
    assert run_cli(root, "init", "--hdd-root", str(hdd)).returncode == 0
    assert run_cli(root, "new", "lora", "exp01").returncode == 0

    # When
    completed = run_cli(
        root,
        "adopt",
        "old-scripts",
        "lora",
        "exp01",
        "--section",
        "code",
        "--yes",
    )

    # Then
    assert completed.returncode == 0
    adopted = root / "methods" / "lora" / "experiments" / "exp01" / "2_code" / "old-scripts"
    assert (adopted / "train.py").is_file()
