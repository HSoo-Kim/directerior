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
