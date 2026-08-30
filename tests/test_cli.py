from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPOSITORY = Path(__file__).parents[1]


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(REPOSITORY), "directerior", *args],
        cwd=root,
        capture_output=True,
        check=False,
        text=True,
    )


def test_installed_entry_point_help_init_new_and_status(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    hdd = tmp_path / "hdd"
    hdd.mkdir()

    help_result = _run(root, "--help")
    assert help_result.returncode == 0
    assert help_result.stdout.startswith("usage: directerior")
    assert "recover" in help_result.stdout
    assert "upgrade-config" in help_result.stdout

    initialized = _run(root, "init", "--hdd-root", str(hdd))
    assert initialized.returncode == 0
    created = _run(root, "new", "lora", "exp01")
    assert created.returncode == 0
    status = _run(root, "status", "--json")

    assert status.returncode == 0
    payload = json.loads(status.stdout)
    assert payload["entries"][0]["label"] == "lora/exp01"
    assert payload["entries"][0]["verified"] is None
