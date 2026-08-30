from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Protocol

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "expman.py"
sys.path.insert(0, str(SCRIPT.parent))

class ProjectFactory(Protocol):
    def __call__(
        self, layout: Literal["legacy", "numbered"], root_name: str = "project"
    ) -> Path: ...


@pytest.fixture(autouse=True)
def isolated_state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIRECTERIOR_STATE_HOME", str(tmp_path / "directerior-state"))

@pytest.fixture
def project_factory(tmp_path: Path) -> ProjectFactory:
    def create(layout: Literal["legacy", "numbered"], root_name: str = "project") -> Path:
        root = tmp_path / root_name
        root.mkdir()
        hdd = tmp_path / f"{root_name}-hdd"
        hdd.mkdir()
        sections = (
            {"plan": "1_plan", "code": "2_code", "results": "3_results"}
            if layout == "numbered"
            else {"plan": "", "code": "code", "results": "results"}
        )
        raw: dict[str, object] = {
            "hdd_root": str(hdd),
            "threshold_mb": 100,
            "hierarchy": ["methods", "experiments"],
        }
        if layout == "numbered":
            raw["sections"] = sections
        (root / ".expman.json").write_text(json.dumps(raw), encoding="utf-8")
        leaf = root / "methods" / "lora" / "experiments" / "exp01"
        for section in sections.values():
            if section:
                (leaf / section).mkdir(parents=True, exist_ok=True)
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

    return create


@pytest.fixture
def project(project_factory: ProjectFactory) -> Path:
    return project_factory("legacy")


@pytest.fixture
def numbered_project(project_factory: ProjectFactory) -> Path:
    return project_factory("numbered")


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
