"""Read-only safety guards.

Directerior manages directories; it never rewrites source code. These guards
keep that promise enforceable: they refuse to touch agent instruction files,
report references that a move would break instead of repairing them, and use
git as the transaction boundary for projects that have one.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

from directerior_core import DirecteriorError

AGENT_FILES: Final = frozenset(
    {
        "agents.md",
        "claude.md",
        "codex.md",
        "copilot-instructions.md",
        "gemini.md",
        "opencode.md",
        "qwen.md",
        "skill.md",
        ".cursorrules",
        ".windsurfrules",
    }
)
AGENT_DIRS: Final = frozenset(
    {
        ".agents",
        ".claude",
        ".codex",
        ".continue",
        ".cursor",
        ".gemini",
        ".opencode",
        ".windsurf",
    }
)
SKIP_DIRS: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "venv",
        ".venv",
    }
)
SOURCE_SUFFIXES: Final = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".go",
        ".h",
        ".hpp",
        ".ipynb",
        ".java",
        ".jl",
        ".js",
        ".m",
        ".py",
        ".r",
        ".rs",
        ".scala",
        ".sh",
        ".ts",
        ".tsx",
    }
)
EXISTING_PROJECT_SOURCE_FILES: Final = 20
MAX_SCAN_BYTES: Final = 2 * 1024 * 1024
MAX_REPORTED_REFERENCES: Final = 40


def require_approval(approved: bool, operation: str) -> None:
    if not approved:
        raise DirecteriorError(
            f"{operation} deletes or relocates data; pass --yes only AFTER explicit user approval"
        )


def is_agent_asset(path: Path) -> bool:
    if path.name.lower() in AGENT_FILES:
        return True
    return bool({part.lower() for part in path.parts} & AGENT_DIRS)


def find_agent_asset(path: Path) -> Path | None:
    if is_agent_asset(path):
        return path
    if not path.is_dir() or path.is_symlink():
        return None
    for candidate in sorted(path.rglob("*")):
        if is_agent_asset(candidate):
            return candidate
    return None


def require_no_agent_assets(path: Path, operation: str) -> None:
    found = find_agent_asset(path)
    if found is not None:
        raise DirecteriorError(
            f"{operation} refuses to touch agent instruction assets: {found}\n"
            "  directerior never moves, deletes, or rewrites agent-facing files "
            "(AGENTS.md, CLAUDE.md, .claude/, ...); relocate it yourself first"
        )


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def git_head(root: Path) -> str | None:
    if _git(root, "rev-parse", "--show-toplevel") is None:
        return None
    return _git(root, "rev-parse", "HEAD")


def require_clean_worktree(root: Path, operation: str, allow_dirty: bool) -> str | None:
    """Refuse to mutate a dirty git worktree so `git reset` can always undo us.

    Tracked modifications only: `git reset` would clobber them, so they block.
    Untracked files - results dirs, checkpoints - are outside git's reach either
    way and are covered by the operation journal instead.
    """
    head = git_head(root)
    if head is None:
        return None
    status = _git(root, "status", "--porcelain", "--untracked-files=no", "--", ".")
    if status and not allow_dirty:
        preview = "\n".join(f"  {line}" for line in status.splitlines()[:10])
        raise DirecteriorError(
            f"{operation} refuses to run on a dirty git worktree:\n{preview}\n"
            "  commit or stash first so this operation stays revertible, "
            "or pass --allow-dirty"
        )
    return head


def iter_project_files(root: Path) -> Iterator[Path]:
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir()):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                stack.append(entry)
            elif entry.is_file():
                yield entry


def count_source_files(root: Path) -> int:
    return sum(1 for path in iter_project_files(root) if path.suffix.lower() in SOURCE_SUFFIXES)


def require_new_project(root: Path, allow_existing: bool) -> int:
    """Directerior is meant for projects it lays out from the start."""
    count = count_source_files(root)
    if count > EXISTING_PROJECT_SOURCE_FILES and not allow_existing:
        raise DirecteriorError(
            f"{root} already holds {count} source files, so this is an existing codebase.\n"
            "  directerior is recommended for projects started under its layout: it moves\n"
            "  directories but never rewrites imports or hardcoded paths.\n"
            "  For an existing codebase, keep the code where it is and manage only large\n"
            "  outputs (adopt --link / offload), or pass --allow-existing to proceed anyway."
        )
    return count


def _is_probably_text(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\0" not in handle.read(4096)
    except OSError:
        return False


def reference_needles(root: Path, source: Path, section: str) -> list[str]:
    needles: list[str] = []
    try:
        needles.append(source.relative_to(root).as_posix())
    except ValueError:
        needles.append(source.as_posix())
    if section != "results" and source.suffix == ".py":
        needles.extend([f"import {source.stem}", f"from {source.stem}"])
    return needles


def find_references(
    root: Path,
    needles: Sequence[str],
    skip_roots: Sequence[Path],
) -> list[str]:
    resolved_skips = [path.resolve() for path in skip_roots]
    hits: list[str] = []
    for path in iter_project_files(root):
        resolved = path.resolve()
        if any(resolved == skip or skip in resolved.parents for skip in resolved_skips):
            continue
        if path.stat().st_size > MAX_SCAN_BYTES or not _is_probably_text(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            if any(needle in line for needle in needles):
                hits.append(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()[:100]}")
                if len(hits) >= MAX_REPORTED_REFERENCES:
                    return hits
    return hits


def require_no_breaking_references(
    root: Path,
    source: Path,
    section: str,
    skip_roots: Sequence[Path],
    allow_breaking: bool,
) -> None:
    """Report references a move would break. Never repairs them - that is the user's call."""
    if allow_breaking:
        return
    hits = find_references(root, reference_needles(root, source, section), [source, *skip_roots])
    if not hits:
        return
    listing = "\n".join(f"  {hit}" for hit in hits)
    raise DirecteriorError(
        f"moving {source} would break {len(hits)} reference(s):\n{listing}\n"
        "  directerior does not rewrite code, configs, or docs.\n"
        "  Use --link to keep the original path working, fix the references yourself,\n"
        "  or pass --allow-breaking-refs to move anyway."
    )
