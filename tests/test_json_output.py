from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli


def test_scan_json_is_machine_parseable_when_over_threshold(project: Path) -> None:
    # Given
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    with (results / "large.bin").open("wb") as handle:
        handle.seek(101 * 1024 * 1024 - 1)
        handle.write(b"0")

    # When
    completed = run_cli(project, "scan", "--json")

    # Then
    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["threshold_mb"] == 100
    assert payload["entries"] == [
        {
            "names": ["lora", "exp01"],
            "label": "lora/exp01",
            "bytes": 101 * 1024 * 1024,
        }
    ]


def test_status_json_reports_local_and_hdd_locations(project: Path) -> None:
    # Given
    first_status = run_cli(project, "status", "--json")
    assert first_status.returncode == 0
    assert run_cli(project, "offload", "lora", "exp01", "--yes").returncode == 0

    # When
    second_status = run_cli(project, "status", "--json")

    # Then
    local_entry = json.loads(first_status.stdout)["entries"][0]
    hdd_entry = json.loads(second_status.stdout)["entries"][0]
    assert local_entry["location"] == "local"
    assert hdd_entry["location"] == "hdd"
    assert local_entry["local_bytes"] == local_entry["stored_bytes"] == 0
    assert local_entry["verified"] is None
    assert "digest" not in local_entry
    assert hdd_entry["bytes"] == hdd_entry["local_bytes"] == 0
    assert hdd_entry["stored_bytes"] == 0
    assert hdd_entry["verified"] is None
    assert "digest" not in hdd_entry


def test_status_verify_reports_digest_without_changing_byte_meanings(project: Path) -> None:
    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")
    normal = json.loads(run_cli(project, "status", "--json").stdout)["entries"][0]

    completed = run_cli(project, "status", "--json", "--verify")

    assert completed.returncode == 0
    verified = json.loads(completed.stdout)["entries"][0]
    assert verified["label"] == normal["label"]
    assert verified["location"] == normal["location"]
    assert verified["bytes"] == normal["bytes"] == len(b"payload")
    assert verified["local_bytes"] == normal["local_bytes"]
    assert verified["stored_bytes"] == normal["stored_bytes"]
    assert verified["verified"] is True
    assert len(verified["digest"]) == 64


def test_status_verify_rejects_link_to_unexpected_target(project: Path, tmp_path: Path) -> None:
    from directerior_storage import make_link, remove_link

    results = project / "methods" / "lora" / "experiments" / "exp01" / "results"
    (results / "artifact.bin").write_bytes(b"payload")
    assert run_cli(project, "offload", "lora", "exp01", "--yes").returncode == 0
    stray = tmp_path / "stray"
    stray.mkdir()
    remove_link(results)
    make_link(results, stray)

    completed = run_cli(project, "status", "--verify")

    assert completed.returncode == 1
    assert "does not link to expected target" in completed.stderr
