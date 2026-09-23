from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import run_cli


def state_env(tmp_path: Path) -> dict[str, str]:
    return {"DIRECTERIOR_STATE_HOME": str(tmp_path / "state")}


def new_project(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root = tmp_path / "proj"
    root.mkdir()
    hdd = tmp_path / "hdd"
    hdd.mkdir()
    env = state_env(tmp_path)
    assert run_cli(root, "init", "--hdd-root", str(hdd), env=env).returncode == 0
    assert run_cli(root, "new", "lora", "exp01", env=env).returncode == 0
    return root, hdd, env


def git_project(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    root, hdd, env = new_project(tmp_path)
    (root / "train.py").write_text("value = 1\n", encoding="utf-8")
    for args in (
        ("init",),
        ("config", "user.email", "test@example.com"),
        ("config", "user.name", "test"),
        ("add", "-A"),
        ("commit", "-m", "initial"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root, hdd, env


def test_adopt_refuses_agent_instruction_assets(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    stray = root / "stray"
    stray.mkdir()
    (stray / "AGENTS.md").write_text("# rules\n", encoding="utf-8")

    # When
    completed = run_cli(root, "adopt", "stray", "lora", "exp01", "--yes", env=env)

    # Then
    assert completed.returncode == 1
    assert "agent instruction assets" in completed.stderr
    assert (stray / "AGENTS.md").is_file()


def test_adopt_reports_breaking_references_and_moves_nothing(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    outputs = root / "outputs"
    outputs.mkdir()
    (outputs / "run.log").write_text("done\n", encoding="utf-8")
    (root / "train.py").write_text('OUT = "outputs/run.log"\n', encoding="utf-8")

    # When
    completed = run_cli(root, "adopt", "outputs", "lora", "exp01", "--yes", env=env)

    # Then
    assert completed.returncode == 1
    assert "would break 1 reference(s)" in completed.stderr
    assert "train.py:1" in completed.stderr
    assert (outputs / "run.log").is_file()


def test_adopt_detects_backslash_spelled_references(tmp_path: Path) -> None:
    root, _hdd, env = new_project(tmp_path)
    outputs = root / "old" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "run.log").write_text("done\n", encoding="utf-8")
    (root / "train.py").write_text('OUT = r"old\\outputs\\run.log"\n', encoding="utf-8")

    completed = run_cli(root, "adopt", "old/outputs", "lora", "exp01", "--yes", env=env)

    assert completed.returncode == 1
    assert "train.py:1" in completed.stderr
    assert (outputs / "run.log").is_file()


def test_adopt_rejects_destination_name_that_is_a_path(tmp_path: Path) -> None:
    root, _hdd, env = new_project(tmp_path)
    outputs = root / "outputs"
    outputs.mkdir()
    escaped = tmp_path / "escaped"

    completed = run_cli(
        root, "adopt", "outputs", "lora", "exp01", "--as", str(escaped), "--yes", env=env
    )

    assert completed.returncode == 1
    assert "--as" in completed.stderr
    assert outputs.is_dir()
    assert not escaped.exists()


def test_adopt_link_back_skips_the_reference_guard(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    outputs = root / "outputs"
    outputs.mkdir()
    (outputs / "run.log").write_text("done\n", encoding="utf-8")
    (root / "train.py").write_text('OUT = "outputs/run.log"\n', encoding="utf-8")

    # When
    completed = run_cli(root, "adopt", "outputs", "lora", "exp01", "--link", "--yes", env=env)

    # Then
    assert completed.returncode == 0
    assert (outputs / "run.log").read_text(encoding="utf-8") == "done\n"
    destination = root / "methods" / "lora" / "experiments" / "exp01" / "3_results" / "outputs"
    assert (destination / "run.log").is_file()


def test_adopt_proceeds_when_breaking_references_are_explicitly_allowed(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = new_project(tmp_path)
    outputs = root / "outputs"
    outputs.mkdir()
    (outputs / "run.log").write_text("done\n", encoding="utf-8")
    (root / "train.py").write_text('OUT = "outputs/run.log"\n', encoding="utf-8")

    # When
    completed = run_cli(
        root, "adopt", "outputs", "lora", "exp01", "--allow-breaking-refs", "--yes", env=env
    )

    # Then
    assert completed.returncode == 0
    assert not outputs.exists()


def test_init_refuses_an_existing_codebase(tmp_path: Path) -> None:
    # Given
    root = tmp_path / "legacy"
    root.mkdir()
    for index in range(25):
        (root / f"module{index}.py").write_text("value = 1\n", encoding="utf-8")

    # When
    completed = run_cli(root, "init", "--hdd-root", str(tmp_path / "hdd"), env=state_env(tmp_path))

    # Then
    assert completed.returncode == 1
    assert "existing codebase" in completed.stderr
    assert not (root / ".expman.json").exists()


def test_init_on_existing_codebase_proceeds_with_explicit_flag(tmp_path: Path) -> None:
    # Given
    root = tmp_path / "legacy"
    root.mkdir()
    for index in range(25):
        (root / f"module{index}.py").write_text("value = 1\n", encoding="utf-8")

    # When
    completed = run_cli(
        root,
        "init",
        "--hdd-root",
        str(tmp_path / "hdd"),
        "--allow-existing",
        env=state_env(tmp_path),
    )

    # Then
    assert completed.returncode == 0
    assert (root / ".expman.json").is_file()
    assert "stay unmanaged" in completed.stdout


def test_tracked_modification_blocks_data_relocation(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = git_project(tmp_path)
    (root / "train.py").write_text("value = 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)

    # When
    completed = run_cli(root, "rm", "lora", "exp01", "--yes", env=env)

    # Then
    assert completed.returncode == 1
    assert "dirty git worktree" in completed.stderr
    assert (root / "methods" / "lora" / "experiments" / "exp01").is_dir()


def test_untracked_results_do_not_block_offload(tmp_path: Path) -> None:
    # Given
    root, _hdd, env = git_project(tmp_path)
    results = root / "methods" / "lora" / "experiments" / "exp01" / "3_results"
    (results / "artifact.bin").write_bytes(b"payload")

    # When
    completed = run_cli(root, "offload", "lora", "exp01", "--yes", env=env)

    # Then
    assert completed.returncode == 0
    assert (results / "artifact.bin").read_bytes() == b"payload"
