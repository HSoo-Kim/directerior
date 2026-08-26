from __future__ import annotations

import shutil
from pathlib import Path

from conftest import run_cli


def test_offload_requires_explicit_approval(project: Path) -> None:
    # Given
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")

    # When
    completed = run_cli(project, "offload", "lora", "exp01")

    # Then
    assert completed.returncode == 1
    assert results.is_dir()
    assert (results / "artifact.bin").read_bytes() == b"payload"


def test_offload_refuses_when_target_has_insufficient_space(
    project: Path,
    monkeypatch,
) -> None:
    # Given
    import directerior_storage
    import expman

    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")
    monkeypatch.chdir(project)
    usage = shutil.disk_usage(project)._replace(free=0)
    monkeypatch.setattr(
        directerior_storage.shutil,
        "disk_usage",
        lambda _path: usage,
    )

    # When
    exit_code = expman.main(["offload", "lora", "exp01", "--yes"])

    # Then
    assert exit_code == 1
    assert (results / "artifact.bin").read_bytes() == b"payload"


def test_offload_warns_when_target_is_on_same_volume(project: Path) -> None:
    # Given
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")

    # When
    completed = run_cli(project, "offload", "lora", "exp01", "--yes")

    # Then
    assert completed.returncode == 0
    assert "same volume" in completed.stderr


def test_restore_requires_approval_before_hdd_source_deletion(project: Path) -> None:
    # Given
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")
    assert run_cli(project, "offload", "lora", "exp01", "--yes").returncode == 0

    # When
    completed = run_cli(project, "restore", "lora", "exp01")

    # Then
    assert completed.returncode == 1
    assert (results / "artifact.bin").read_bytes() == b"payload"


def test_offload_preserves_source_when_copy_verification_fails(
    project: Path,
    monkeypatch,
) -> None:
    # Given
    import directerior_storage
    import expman

    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        directerior_storage,
        "verify_tree_copy",
        lambda _source, _target: False,
    )

    # When
    exit_code = expman.main(["offload", "lora", "exp01", "--yes"])

    # Then
    assert exit_code == 1
    assert results.is_dir()
    assert (results / "artifact.bin").read_bytes() == b"payload"
