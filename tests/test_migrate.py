from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli


def state_env(tmp_path: Path) -> dict[str, str]:
    return {"DIRECTERIOR_STATE_HOME": str(tmp_path / "state")}


def latest_history_id(project: Path, env: dict[str, str]) -> str:
    completed = run_cli(project, "history", "--json", env=env)
    assert completed.returncode == 0
    return json.loads(completed.stdout)["entries"][0]["id"]


def test_migrate_dry_run_changes_nothing(project: Path, tmp_path: Path) -> None:
    # Given
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    before_config = (project / ".expman.json").read_bytes()
    env = state_env(tmp_path)

    # When
    completed = run_cli(project, "migrate-layout", "--dry-run", env=env)

    # Then
    assert completed.returncode == 0
    assert "1_plan" in completed.stdout
    assert (project / ".expman.json").read_bytes() == before_config
    assert (leaf / "code").is_dir()
    assert not (leaf / "1_plan").exists()
    assert not Path(env["DIRECTERIOR_STATE_HOME"]).exists()


def test_history_records_applied_migration(project: Path, tmp_path: Path) -> None:
    # Given
    env = state_env(tmp_path)
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0

    # When
    completed = run_cli(project, "history", "--json", env=env)

    # Then
    assert completed.returncode == 0
    entries = json.loads(completed.stdout)["entries"]
    assert len(entries) == 1
    assert entries[0]["state"] == "applied"


def test_history_exposes_graph_metadata(project: Path, tmp_path: Path) -> None:
    # Given
    env = state_env(tmp_path)
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0

    # When
    completed = run_cli(project, "history", "--json", env=env)

    # Then
    entry = json.loads(completed.stdout)["entries"][0]
    assert entry["operation_type"] == "migrate_layout"
    assert entry["parent_id"] is None
    assert len(entry["before_fingerprint"]) == 64
    assert len(entry["after_fingerprint"]) == 64
    assert entry["before_fingerprint"] != entry["after_fingerprint"]


def test_graph_metadata_survives_undo_redo(project: Path, tmp_path: Path) -> None:
    # Given
    env = state_env(tmp_path)
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0
    before = json.loads(run_cli(project, "history", "--json", env=env).stdout)["entries"][0]

    # When
    assert run_cli(project, "undo", "latest", "--yes", env=env).returncode == 0
    assert run_cli(project, "redo", "latest", "--yes", env=env).returncode == 0

    # Then
    after = json.loads(run_cli(project, "history", "--json", env=env).stdout)["entries"][0]
    assert after["parent_id"] == before["parent_id"]
    assert after["before_fingerprint"] == before["before_fingerprint"]
    assert after["after_fingerprint"] == before["after_fingerprint"]


def test_schema_one_journal_is_upgraded_when_loaded(project: Path, tmp_path: Path) -> None:
    # Given
    env = state_env(tmp_path)
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0
    journal = next(Path(env["DIRECTERIOR_STATE_HOME"]).rglob("*.json"))
    raw = json.loads(journal.read_text(encoding="utf-8"))
    raw["schema"] = 1
    for field in (
        "operation_type",
        "parent_id",
        "before_fingerprint",
        "after_fingerprint",
    ):
        raw.pop(field, None)
    journal.write_text(json.dumps(raw), encoding="utf-8")

    # When
    completed = run_cli(project, "history", "--json", env=env)

    # Then
    entry = json.loads(completed.stdout)["entries"][0]
    assert entry["operation_type"] == "migrate_layout"
    assert len(entry["before_fingerprint"]) == 64
    assert len(entry["after_fingerprint"]) == 64


def test_parent_selector_links_matching_result_state(
    project: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Given
    import directerior_history

    env = state_env(tmp_path)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", env["DIRECTERIOR_STATE_HOME"])
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0
    operation = directerior_history.load_record(project, "latest")

    # When
    parent_id = directerior_history.find_parent_id(
        [operation],
        operation.after_fingerprint,
    )

    # Then
    assert parent_id == operation.operation_id


def test_migrate_layout_requires_explicit_approval(project: Path) -> None:
    # Given
    leaf = project / "methods" / "lora" / "experiments" / "exp01"

    # When
    completed = run_cli(project, "migrate-layout")

    # Then
    assert completed.returncode == 1
    assert (leaf / "code").is_dir()
    assert (leaf / "results").is_dir()


def test_migrate_layout_converts_legacy_leaf(project: Path) -> None:
    # Given
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "code" / "train.py").write_text("print('train')\n", encoding="utf-8")
    (leaf / "results" / "metric.json").write_text("{}\n", encoding="utf-8")

    # When
    completed = run_cli(project, "migrate-layout", "--yes")

    # Then
    assert completed.returncode == 0
    assert (leaf / "2_code" / "train.py").is_file()
    assert (leaf / "3_results" / "metric.json").is_file()
    assert (leaf / "1_plan" / "1_objective.md").is_file()
    config = json.loads((project / ".expman.json").read_text(encoding="utf-8"))
    assert config["sections"] == {
        "plan": "1_plan",
        "code": "2_code",
        "results": "3_results",
    }


def test_migrate_layout_moves_offloaded_hdd_mirror(project: Path) -> None:
    # Given
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "results" / "artifact.bin").write_bytes(b"payload")
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
    new_target = old_target.with_name("3_results")

    # When
    completed = run_cli(project, "migrate-layout", "--yes")

    # Then
    assert completed.returncode == 0
    assert not old_target.exists()
    assert (new_target / "artifact.bin").read_bytes() == b"payload"
    assert (leaf / "3_results" / "artifact.bin").read_bytes() == b"payload"


def test_undo_restores_exact_legacy_layout_and_redo_reapplies(
    project: Path,
    tmp_path: Path,
) -> None:
    # Given
    env = state_env(tmp_path)
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "code" / "train.py").write_bytes(b"original-code")
    (leaf / "results" / "metric.json").write_bytes(b'{"score": 1}')
    before_config = (project / ".expman.json").read_bytes()
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0
    operation_id = latest_history_id(project, env)

    # When
    undone = run_cli(project, "undo", operation_id, "--yes", env=env)

    # Then
    assert undone.returncode == 0
    assert (project / ".expman.json").read_bytes() == before_config
    assert (leaf / "code" / "train.py").read_bytes() == b"original-code"
    assert (leaf / "results" / "metric.json").read_bytes() == b'{"score": 1}'
    assert not (leaf / "1_plan").exists()
    redone = run_cli(project, "redo", operation_id, "--yes", env=env)
    assert redone.returncode == 0
    assert (leaf / "2_code" / "train.py").read_bytes() == b"original-code"
    assert (leaf / "3_results" / "metric.json").read_bytes() == b'{"score": 1}'
    assert (leaf / "1_plan").is_dir()


def test_undo_refuses_when_migrated_data_changed(project: Path, tmp_path: Path) -> None:
    # Given
    env = state_env(tmp_path)
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "code" / "train.py").write_bytes(b"original-code")
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0
    operation_id = latest_history_id(project, env)
    (leaf / "2_code" / "train.py").write_bytes(b"changed-after-migration")
    migrated_config = (project / ".expman.json").read_bytes()

    # When
    completed = run_cli(project, "undo", operation_id, "--yes", env=env)

    # Then
    assert completed.returncode == 1
    assert "changed since migration" in completed.stderr
    assert (project / ".expman.json").read_bytes() == migrated_config
    assert (leaf / "2_code" / "train.py").read_bytes() == b"changed-after-migration"
    assert not (leaf / "code").exists()


def test_undo_refuses_when_empty_directory_was_added(project: Path, tmp_path: Path) -> None:
    # Given
    env = state_env(tmp_path)
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0
    operation_id = latest_history_id(project, env)
    (leaf / "2_code" / "new-empty-dir").mkdir()

    # When
    completed = run_cli(project, "undo", operation_id, "--yes", env=env)

    # Then
    assert completed.returncode == 1
    assert (leaf / "2_code" / "new-empty-dir").is_dir()


def test_offloaded_undo_redo_restores_hdd_paths(project: Path, tmp_path: Path) -> None:
    # Given
    env = state_env(tmp_path)
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "results" / "artifact.bin").write_bytes(b"payload")
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
    new_target = old_target.with_name("3_results")
    assert run_cli(project, "migrate-layout", "--yes", env=env).returncode == 0
    operation_id = latest_history_id(project, env)

    # When
    undone = run_cli(project, "undo", operation_id, "--yes", env=env)

    # Then
    assert undone.returncode == 0
    assert (old_target / "artifact.bin").read_bytes() == b"payload"
    assert not new_target.exists()
    assert (leaf / "results" / "artifact.bin").read_bytes() == b"payload"
    assert run_cli(project, "redo", operation_id, "--yes", env=env).returncode == 0
    assert not old_target.exists()
    assert (new_target / "artifact.bin").read_bytes() == b"payload"
    assert (leaf / "3_results" / "artifact.bin").read_bytes() == b"payload"
