import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_skill_requires_numbered_purpose_specific_request_directories() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Every visible directory authored by the agent MUST have an ordering prefix" in skill
    assert "Directory names MUST describe the directory's purpose or research activity" in skill
    assert "Keep every artifact produced for one request beneath that request's numbered" in skill


def test_skill_rejects_fake_experiments_for_non_experiment_work() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Never disguises non-experiment work as an experiment" in skill
    assert re.search(r"Do not create a\s+fake method or `expNN-\*` leaf", skill)
