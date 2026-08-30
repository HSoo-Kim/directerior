from __future__ import annotations

import json
from pathlib import Path

import directerior_ops
import pytest
from directerior_core import DirecteriorError
from directerior_history import OperationRecord, list_operation_records
from directerior_lifecycle import offload, remove_experiment, rename_experiment, restore
from directerior_ops import recover_operation
from directerior_project import adopt_output


class InjectedFailure(RuntimeError):
    pass


RENAME_STATES = [
    "prepared",
    "link_removed",
    "local_renamed",
    "hdd_renamed",
    "linked",
    "manifest_updated",
]


def _fail_after_state(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    original = directerior_ops.save_operation_record
    fired = False

    def save_then_fail(record: OperationRecord) -> None:
        nonlocal fired
        if not fired and record.state == state and state != "prepared":
            fired = True
            raise InjectedFailure(state)
        original(record)
        if not fired and record.state == "prepared" and state == "prepared":
            fired = True
            raise InjectedFailure(state)

    monkeypatch.setattr(directerior_ops, "save_operation_record", save_then_fail)


def _latest(root: Path) -> OperationRecord:
    return list_operation_records(root)[0]


def _journal_state_after_crash(state: str, sequence: list[str]) -> str:
    return state if state == "prepared" else sequence[sequence.index(state) - 1]

@pytest.mark.parametrize("state", ["prepared", "copied", "verified", "source_removed", "linked"])
def test_offload_recovers_after_each_boundary(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "data.bin").write_bytes(b"payload")
    _fail_after_state(monkeypatch, state)

    with pytest.raises(InjectedFailure):
        offload(["lora", "exp01"], True)

    interrupted = _latest(project)
    assert results.exists() or Path(str(interrupted.details["target"])).exists()
    assert interrupted.state == _journal_state_after_crash(
        state, ["prepared", "copied", "verified", "source_removed", "linked"]
    )
    recovered = recover_operation(project, interrupted.operation_id, True)

    assert recovered.state == "committed"
    assert (results / "data.bin").read_bytes() == b"payload"
    assert _latest(project).state == "committed"


@pytest.mark.parametrize(
    "state", ["prepared", "copied", "verified", "link_removed", "local_installed", "hdd_removed"]
)
def test_restore_recovers_after_each_boundary(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "data.bin").write_bytes(b"payload")
    offload(["lora", "exp01"], True)
    _fail_after_state(monkeypatch, state)

    with pytest.raises(InjectedFailure):
        restore(["lora", "exp01"], True)

    interrupted = _latest(project)
    assert interrupted.state == _journal_state_after_crash(
        state,
        [
            "prepared",
            "copied",
            "verified",
            "link_removed",
            "local_installed",
            "hdd_removed",
        ],
    )
    recovered = recover_operation(project, interrupted.operation_id, True)

    assert recovered.state == "committed"
    assert not results.is_symlink()
    assert (results / "data.bin").read_bytes() == b"payload"


def test_restore_preflight_refuses_changed_source_without_mutation(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "data.bin").write_bytes(b"payload")
    offload(["lora", "exp01"], True)
    _fail_after_state(monkeypatch, "link_removed")

    with pytest.raises(InjectedFailure):
        restore(["lora", "exp01"], True)

    interrupted = _latest(project)
    assert interrupted.state == "verified"
    source = Path(str(interrupted.details["source"]))
    staging = Path(str(interrupted.details["staging"]))
    (source / "data.bin").write_bytes(b"changed")
    positions = (
        results.exists(),
        directerior_ops.is_offloaded(results),
        source.exists(),
        staging.exists(),
    )

    with pytest.raises(DirecteriorError, match="recovery conflict"):
        recover_operation(project, interrupted.operation_id, True)

    assert (
        results.exists(),
        directerior_ops.is_offloaded(results),
        source.exists(),
        staging.exists(),
    ) == positions
    assert (source / "data.bin").read_bytes() == b"changed"
    assert (staging / "data.bin").read_bytes() == b"payload"
    assert _latest(project).state == "verified"




@pytest.mark.parametrize("state", RENAME_STATES)
def test_rename_recovers_after_each_boundary(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    old = project / "methods" / "lora" / "experiments" / "exp01"
    (old / "results" / "data.bin").write_bytes(b"payload")
    _fail_after_state(monkeypatch, state)

    with pytest.raises(InjectedFailure):
        rename_experiment(["lora", "exp01"], ["lora", "exp02"], True)

    interrupted = _latest(project)
    assert interrupted.state == _journal_state_after_crash(
        state,
        [
            "prepared",
            "link_removed",
            "local_renamed",
            "hdd_renamed",
            "linked",
            "manifest_updated",
        ],
    )
    recovered = recover_operation(project, interrupted.operation_id, True)
    new = project / "methods" / "lora" / "experiments" / "exp02"

    assert recovered.state == "committed"
    assert not old.exists()
    assert (new / "results" / "data.bin").read_bytes() == b"payload"


@pytest.mark.parametrize("state", RENAME_STATES)
def test_rename_recovery_refuses_modified_local_tree(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    old = project / "methods" / "lora" / "experiments" / "exp01"
    new = project / "methods" / "lora" / "experiments" / "exp02"
    script = old / "code" / "train.py"
    script.write_text("original\n", encoding="utf-8")
    _fail_after_state(monkeypatch, state)

    with pytest.raises(InjectedFailure):
        rename_experiment(["lora", "exp01"], ["lora", "exp02"], True)

    interrupted = _latest(project)
    current = old if old.exists() else new
    changed = current / "code" / "train.py"
    changed.write_text("changed\n", encoding="utf-8")
    positions = (old.exists(), new.exists())

    with pytest.raises(DirecteriorError, match="recovery conflict"):
        recover_operation(project, interrupted.operation_id, True)

    assert (old.exists(), new.exists()) == positions
    assert changed.read_text(encoding="utf-8") == "changed\n"


@pytest.mark.parametrize("state", RENAME_STATES)
def test_rename_recovery_refuses_modified_hdd_tree(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    old = project / "methods" / "lora" / "experiments" / "exp01"
    new = project / "methods" / "lora" / "experiments" / "exp02"
    (old / "results" / "data.bin").write_bytes(b"original")
    offload(["lora", "exp01"], True)
    _fail_after_state(monkeypatch, state)

    with pytest.raises(InjectedFailure):
        rename_experiment(["lora", "exp01"], ["lora", "exp02"], True)

    interrupted = _latest(project)
    old_target = Path(str(interrupted.details["old_target"]))
    new_target = Path(str(interrupted.details["new_target"]))
    current_target = old_target if old_target.exists() else new_target
    changed = current_target / "data.bin"
    changed.write_bytes(b"changed")
    positions = (
        old.exists(),
        new.exists(),
        old_target.exists(),
        new_target.exists(),
    )

    with pytest.raises(DirecteriorError, match="recovery conflict"):
        recover_operation(project, interrupted.operation_id, True)

    assert (
        old.exists(),
        new.exists(),
        old_target.exists(),
        new_target.exists(),
    ) == positions
    assert changed.read_bytes() == b"changed"


def test_rename_recovery_refuses_manifest_mutation_after_rewrite(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    new = project / "methods" / "lora" / "experiments" / "exp02"
    _fail_after_state(monkeypatch, "committed")

    with pytest.raises(InjectedFailure):
        rename_experiment(["lora", "exp01"], ["lora", "exp02"], True)

    interrupted = _latest(project)
    assert interrupted.state == "manifest_updated"
    manifest = new / "manifest.json"
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["description"] = "changed after rename"
    manifest.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DirecteriorError, match="recovery conflict"):
        recover_operation(project, interrupted.operation_id, True)

    assert _latest(project).state == "manifest_updated"
    assert json.loads(manifest.read_text(encoding="utf-8"))["description"] == (
        "changed after rename"
    )



@pytest.mark.parametrize(
    "state", ["prepared", "destination_ready", "verified", "source_removed", "linked"]
)
def test_cross_volume_adopt_recovers_after_each_boundary(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    source = tmp_path / "outside"
    source.mkdir()
    (source / "data.bin").write_bytes(b"payload")
    monkeypatch.setattr(directerior_ops, "same_volume", lambda *_args: False)
    _fail_after_state(monkeypatch, state)

    with pytest.raises(InjectedFailure):
        adopt_output(str(source), ["lora", "exp01"], "adopted", True, True, "results")

    interrupted = _latest(project)
    recovered = recover_operation(project, interrupted.operation_id, True)
    assert interrupted.state == _journal_state_after_crash(
        state, ["prepared", "destination_ready", "verified", "source_removed", "linked"]
    )
    destination = project / "methods" / "lora" / "experiments" / "exp01" / "results" / "adopted"

    assert recovered.state == "committed"
    assert (destination / "data.bin").read_bytes() == b"payload"
    assert (source / "data.bin").read_bytes() == b"payload"


def test_remove_preflight_refuses_changed_local_tree_without_mutation(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    results = leaf / "results"
    code = leaf / "code" / "train.py"
    code.write_bytes(b"original")
    (results / "data.bin").write_bytes(b"payload")
    offload(["lora", "exp01"], True)
    _fail_after_state(monkeypatch, "hdd_trashed")

    with pytest.raises(InjectedFailure):
        remove_experiment(["lora", "exp01"], True)

    interrupted = _latest(project)
    assert interrupted.state == "prepared"
    target = Path(str(interrupted.details["target"]))
    hdd_trash = Path(str(interrupted.details["hdd_trash"]))
    local_trash = Path(str(interrupted.details["local_trash"]))
    expected_link = directerior_ops.link_target(results)
    code.write_bytes(b"changed")
    positions = (
        leaf.exists(),
        target.exists(),
        hdd_trash.exists(),
        local_trash.exists(),
        directerior_ops.link_target(results),
    )

    with pytest.raises(DirecteriorError, match="recovery conflict"):
        recover_operation(project, interrupted.operation_id, True)

    assert (
        leaf.exists(),
        target.exists(),
        hdd_trash.exists(),
        local_trash.exists(),
        directerior_ops.link_target(results),
    ) == positions
    assert directerior_ops.link_target(results) == expected_link
    assert code.read_bytes() == b"changed"
    assert (hdd_trash / "data.bin").read_bytes() == b"payload"
    assert _latest(project).state == "prepared"


def test_cross_volume_remove_recovers_after_verified_copy(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "results" / "data.bin").write_bytes(b"payload")
    original_copy = directerior_ops.copy_tree_verified
    copy_calls = 0
    fired = False

    def copy_then_fail(source: Path, target: Path, operation: str = "copy"):
        nonlocal copy_calls, fired
        snapshot = original_copy(source, target, operation)
        if operation == "rm":
            copy_calls += 1
            if not fired:
                fired = True
                raise InjectedFailure("after verified rm copy")
        return snapshot

    monkeypatch.setattr(directerior_ops, "same_volume", lambda *_args: False)
    monkeypatch.setattr(directerior_ops, "copy_tree_verified", copy_then_fail)

    with pytest.raises(InjectedFailure, match="after verified rm copy"):
        remove_experiment(["lora", "exp01"], True)

    interrupted = _latest(project)
    local_trash = Path(str(interrupted.details["local_trash"]))
    assert interrupted.state == "hdd_trashed"
    assert (leaf / "results" / "data.bin").read_bytes() == b"payload"
    assert (local_trash / "results" / "data.bin").read_bytes() == b"payload"

    recovered = recover_operation(project, interrupted.operation_id, True)

    assert recovered.state == "committed"
    assert not leaf.exists()
    assert (local_trash / "results" / "data.bin").read_bytes() == b"payload"
    assert copy_calls == 1


def test_offloaded_remove_recovers_after_saved_hdd_trashed_state(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    results = leaf / "results"
    (results / "data.bin").write_bytes(b"payload")
    offload(["lora", "exp01"], True)
    original_save = directerior_ops.save_operation_record
    fired = False

    def save_then_fail(record: OperationRecord) -> None:
        nonlocal fired
        original_save(record)
        if not fired and record.state == "hdd_trashed":
            fired = True
            raise InjectedFailure("after saved hdd_trashed")

    monkeypatch.setattr(directerior_ops, "save_operation_record", save_then_fail)

    with pytest.raises(InjectedFailure, match="after saved hdd_trashed"):
        remove_experiment(["lora", "exp01"], True)

    interrupted = _latest(project)
    target = Path(str(interrupted.details["target"]))
    local_trash = Path(str(interrupted.details["local_trash"]))
    hdd_trash = Path(str(interrupted.details["hdd_trash"]))
    assert interrupted.state == "hdd_trashed"
    assert directerior_ops.link_target(results) == target.resolve(strict=False)
    assert (hdd_trash / "data.bin").read_bytes() == b"payload"

    recovered = recover_operation(project, interrupted.operation_id, True)

    assert recovered.state == "committed"
    assert not leaf.exists()
    assert local_trash.is_dir()
    assert (hdd_trash / "data.bin").read_bytes() == b"payload"


@pytest.mark.parametrize("state", ["prepared", "hdd_trashed", "local_trashed"])
def test_remove_recovers_after_each_boundary(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "results" / "data.bin").write_bytes(b"payload")
    _fail_after_state(monkeypatch, state)

    with pytest.raises(InjectedFailure):
        remove_experiment(["lora", "exp01"], True)

    interrupted = _latest(project)
    local_trash = Path(str(interrupted.details["local_trash"]))
    assert leaf.exists() or local_trash.exists()
    recovered = recover_operation(project, interrupted.operation_id, True)
    assert interrupted.state == _journal_state_after_crash(
        state, ["prepared", "hdd_trashed", "local_trashed"]
    )

    assert recovered.state == "committed"
    assert not leaf.exists()
    assert (local_trash / "results" / "data.bin").read_bytes() == b"payload"


def test_remove_recovery_refuses_modified_hdd_trash(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "state"))
    leaf = project / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "results" / "data.bin").write_bytes(b"payload")
    offload(["lora", "exp01"], True)
    _fail_after_state(monkeypatch, "hdd_trashed")

    with pytest.raises(InjectedFailure):
        remove_experiment(["lora", "exp01"], True)

    interrupted = _latest(project)
    hdd_trash = Path(str(interrupted.details["hdd_trash"]))
    (hdd_trash / "data.bin").write_bytes(b"changed")

    with pytest.raises(DirecteriorError, match="recovery conflict"):
        recover_operation(project, interrupted.operation_id, True)

    assert leaf.is_dir()
    assert hdd_trash.is_dir()
