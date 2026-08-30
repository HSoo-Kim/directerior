from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import directerior_storage
import pytest
from directerior_core import DirecteriorError, load_config
from directerior_project import scan_entries, status_entries
from directerior_storage import (
    TreeSnapshot,
    copy_file_verified,
    copy_tree_verified,
    directory_size,
    make_link,
    require_disjoint_paths,
)


def test_fast_size_scan_and_status_do_not_open_contents(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    data = results / "large.bin"
    with data.open("wb") as handle:
        handle.truncate(101 * 1024 * 1024)
    config = load_config(project)

    def refuse_data_open(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("content read during metadata-only operation")

    monkeypatch.setattr(Path, "open", refuse_data_open)

    assert scan_entries(project, config)[0]["bytes"] == 101 * 1024 * 1024
    status = status_entries(project, config)[0]
    assert status["local_bytes"] == 101 * 1024 * 1024
    assert status["stored_bytes"] == 101 * 1024 * 1024


def test_directory_size_counts_sparse_and_empty_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "empty.bin").touch()
    with (source / "sparse.bin").open("wb") as handle:
        handle.truncate(8192)

    assert directory_size(source) == 8192


def test_verified_copy_rejects_nested_link(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    make_link(source / "nested", external)

    with pytest.raises(DirecteriorError, match="refuses nested link/reparse point"):
        copy_tree_verified(source, tmp_path / "target", "offload")

    assert not (tmp_path / "target").exists()


def test_disjoint_paths_reject_nested_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(DirecteriorError, match="requires disjoint"):
        require_disjoint_paths(source, source / "archive", "offload")


def test_tree_copy_cleans_target_after_verification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.bin").write_bytes(b"payload")
    target = tmp_path / "target"
    monkeypatch.setattr(directerior_storage, "verify_tree_copy", lambda *_args: False)

    with pytest.raises(DirecteriorError, match="verification failed"):
        copy_tree_verified(source, target)

    assert source.is_dir()
    assert not target.exists()


def test_file_copy_cleans_staging_after_verification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    target = tmp_path / "target.bin"
    real_snapshot = directerior_storage.file_snapshot
    calls = 0

    def mismatched_snapshot(path: Path) -> TreeSnapshot:
        nonlocal calls
        calls += 1
        snapshot = real_snapshot(path)
        if calls == 2:
            return TreeSnapshot(snapshot.file_count, snapshot.byte_count, "mismatch")
        return snapshot

    monkeypatch.setattr(directerior_storage, "file_snapshot", mismatched_snapshot)

    with pytest.raises(DirecteriorError, match="verification failed"):
        copy_file_verified(source, target)

    assert source.read_bytes() == b"payload"
    assert not target.exists()
    assert list(tmp_path.glob(".target.bin.*.tmp")) == []
