from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "expman.py"
sys.path.insert(0, str(SCRIPT.parent))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    hdd = tmp_path / "hdd"
    hdd.mkdir()
    (root / ".expman.json").write_text(
        json.dumps(
            {
                "hdd_root": str(hdd),
                "threshold_mb": 100,
                "hierarchy": ["methods", "experiments"],
            }
        ),
        encoding="utf-8",
    )
    leaf = root / "methods" / "lora" / "experiments" / "exp01"
    (leaf / "code").mkdir(parents=True)
    (leaf / "results").mkdir()
    (leaf / "manifest.json").write_text(
        json.dumps(
            {
                "levels": {"methods": "lora", "experiments": "exp01"},
                "created": "2026-08-26",
                "description": "",
            }
        ),
        encoding="utf-8",
    )
    return root


def run_cli(
    root: Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env is not None:
        process_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=root,
        capture_output=True,
        check=False,
        env=process_env,
        text=True,
    )
