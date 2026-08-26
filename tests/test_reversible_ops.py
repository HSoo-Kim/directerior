from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli
from test_guards import new_project


def latest_operation(root: Path, env: dict[str, str]) -> dict[str, object]:
    completed = run_cli(root, "history", "--json", env=env)
    assert completed.returncode == 0
    entries = json.loads(completed.stdout)["entries"]
    return entries[0]


def test_adopt_is_undoable(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    outputs = root / "outputs"
    outputs.mkdir()
    (outputs / "run.log").write_text("done\n", encoding="utf-8")
    assert run_cli(root, "adopt", "outputs", "lora", "exp01", "--yes", env=env).returncode == 0
    results = root / "methods" / "lora" / "experiments" / "exp01" / "3_results"
    assert not outputs.exists()

    # When
    completed = run_cli(root, "undo", "latest", "--yes", env=env)

    # Then
    assert completed.returncode == 0
    assert (outputs / "run.log").read_text(encoding="utf-8") == "done\n"
    assert not (results / "outputs").exists()
    assert results.is_dir()


def test_undo_removes_the_link_left_by_adopt(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    outputs = root / "outputs"
    outputs.mkdir()
    (outputs / "run.log").write_text("done\n", encoding="utf-8")
    arguments = ("adopt", "outputs", "lora", "exp01", "--link", "--yes")
    assert run_cli(root, *arguments, env=env).returncode == 0

    # When
    completed = run_cli(root, "undo", "latest", "--yes", env=env)

    # Then
    assert completed.returncode == 0
    assert not outputs.is_symlink()
    assert (outputs / "run.log").read_text(encoding="utf-8") == "done\n"


def test_rm_moves_the_experiment_to_trash_instead_of_deleting_it(tmp_path: Path) -> None:
    # Given
    root, hdd, env = new_project(tmp_path)
    leaf = root / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "3_results" / "artifact.bin").write_bytes(b"payload")

    # When
    completed = run_cli(root, "rm", "lora", "exp01", "--yes", env=env)

    # Then
    assert completed.returncode == 0
    assert not leaf.exists()
    trashed = hdd / ".trash" / root.name
    recovered = next(trashed.rglob("artifact.bin"))
    assert recovered.read_bytes() == b"payload"


def test_undo_restores_a_removed_experiment(tmp_path: Path) -> None:
    # Given
    root, hdd, env = new_project(tmp_path)
    leaf = root / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "3_results" / "artifact.bin").write_bytes(b"payload")
    assert run_cli(root, "rm", "lora", "exp01", "--yes", env=env).returncode == 0

    # When
    completed = run_cli(root, "undo", "latest", "--yes", env=env)

    # Then
    assert completed.returncode == 0
    assert (leaf / "3_results" / "artifact.bin").read_bytes() == b"payload"
    assert (leaf / "manifest.json").is_file()
    assert not any((hdd / ".trash" / root.name).iterdir())


def test_undo_restores_an_offloaded_experiment_with_its_link(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    leaf = root / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "3_results" / "artifact.bin").write_bytes(b"payload")
    assert run_cli(root, "offload", "lora", "exp01", "--yes", env=env).returncode == 0
    assert run_cli(root, "rm", "lora", "exp01", "--yes", env=env).returncode == 0

    # When
    completed = run_cli(root, "undo", "latest", "--yes", env=env)

    # Then
    assert completed.returncode == 0
    assert (leaf / "3_results" / "artifact.bin").read_bytes() == b"payload"
    status = run_cli(root, "status", "--json", env=env)
    assert json.loads(status.stdout)["entries"][0]["location"] == "hdd"


def test_purge_deletes_permanently_without_a_journal(tmp_path: Path) -> None:
    # Given
    root, hdd, env = new_project(tmp_path)
    leaf = root / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "3_results" / "artifact.bin").write_bytes(b"payload")

    # When
    completed = run_cli(root, "rm", "lora", "exp01", "--yes", "--purge", env=env)

    # Then
    assert completed.returncode == 0
    assert "no undo" in completed.stdout
    assert not leaf.exists()
    assert not (hdd / ".trash").exists()
    assert json.loads(run_cli(root, "history", "--json", env=env).stdout)["entries"] == []


def test_undo_refuses_when_the_moved_data_changed(tmp_path: Path) -> None:
    # Given
    root, hdd, env = new_project(tmp_path)
    (root / "outputs").mkdir()
    (root / "outputs" / "run.log").write_text("done\n", encoding="utf-8")
    assert run_cli(root, "adopt", "outputs", "lora", "exp01", "--yes", env=env).returncode == 0
    destination = root / "methods" / "lora" / "experiments" / "exp01" / "3_results" / "outputs"
    (destination / "extra.log").write_text("late\n", encoding="utf-8")

    # When
    completed = run_cli(root, "undo", "latest", "--yes", env=env)

    # Then
    assert completed.returncode == 1
    assert "changed since adopt" in completed.stderr
    assert (destination / "run.log").is_file()
    assert not (hdd / ".trash").exists()


def test_history_lists_path_operations(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    (root / "outputs").mkdir()
    (root / "outputs" / "run.log").write_text("done\n", encoding="utf-8")

    # When
    assert run_cli(root, "adopt", "outputs", "lora", "exp01", "--yes", env=env).returncode == 0

    # Then
    entry = latest_operation(root, env)
    assert entry["operation_type"] == "adopt"
    assert entry["state"] == "applied"


def test_undo_requires_its_own_approval(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    (root / "outputs").mkdir()
    (root / "outputs" / "run.log").write_text("done\n", encoding="utf-8")
    assert run_cli(root, "adopt", "outputs", "lora", "exp01", "--yes", env=env).returncode == 0

    # When
    completed = run_cli(root, "undo", "latest", env=env)

    # Then
    assert completed.returncode == 1
    assert not (root / "outputs").exists()
