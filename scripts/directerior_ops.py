"""Reversible journal for path operations (`adopt`, `rm`).

Migrations have their own journal in `directerior_history`. These records cover
the two commands that used to be one-way doors: `adopt` moved data with no way
back, and `rm` deleted it outright.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from directerior_core import DirecteriorError
from directerior_guards import require_approval
from directerior_history import new_operation_id, project_history_dir
from directerior_storage import make_link, remove_link

KIND = "path_op"
TRASH_DIR = ".trash"


@dataclass(frozen=True, slots=True)
class PathMove:
    source: str
    destination: str
    is_dir: bool
    digest: str
    linked_back: bool


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    state: str
    operation_type: str
    project_root: str
    created_at: str
    git_head: str | None
    moves: tuple[PathMove, ...]
    relink: tuple[str, str] | None = None


def structure_digest(path: Path) -> str:
    """Fingerprint names and sizes only.

    A journalled move never rewrites bytes, so structure is what undo must
    verify. Content hashing stays in `directerior_storage`, where transfers
    actually copy data. `lstat` keeps dangling symlinks from raising.
    """
    digest = hashlib.sha256()
    if not path.is_dir() or path.is_symlink():
        digest.update(b"F\0" + path.name.encode("utf-8") + str(path.lstat().st_size).encode())
        return digest.hexdigest()
    for directory, subdirs, filenames in os.walk(path):
        subdirs.sort()
        base = Path(directory)
        for subdir in subdirs:
            relative = (base / subdir).relative_to(path).as_posix()
            digest.update(b"D\0" + relative.encode("utf-8"))
        for filename in sorted(filenames):
            entry = base / filename
            relative = entry.relative_to(path).as_posix()
            digest.update(b"F\0" + relative.encode("utf-8") + str(entry.lstat().st_size).encode())
    return digest.hexdigest()


def new_record(
    operation_type: str,
    root: Path,
    git_head: str | None,
    moves: tuple[PathMove, ...],
    relink: tuple[str, str] | None = None,
    operation_id: str | None = None,
) -> OperationRecord:
    return OperationRecord(
        operation_id=operation_id or new_operation_id(),
        state="applied",
        operation_type=operation_type,
        project_root=str(root),
        created_at=datetime.now(timezone.utc).isoformat(),
        git_head=git_head,
        moves=moves,
        relink=relink,
    )


def save_operation(record: OperationRecord) -> None:
    directory = project_history_dir(Path(record.project_root))
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 2, "kind": KIND, "id": record.operation_id, **asdict(record)}
    target = directory / f"{record.operation_id}.json"
    staging = target.with_suffix(".json.tmp")
    staging.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    staging.replace(target)


def _from_payload(raw: dict[str, object]) -> OperationRecord:
    moves = tuple(
        PathMove(
            source=str(move["source"]),
            destination=str(move["destination"]),
            is_dir=bool(move["is_dir"]),
            digest=str(move["digest"]),
            linked_back=bool(move["linked_back"]),
        )
        for move in raw["moves"]  # pyright: ignore[reportGeneralTypeIssues]
    )
    relink_raw = raw.get("relink")
    relink = (
        (str(relink_raw[0]), str(relink_raw[1]))  # pyright: ignore[reportIndexIssue]
        if relink_raw is not None
        else None
    )
    return OperationRecord(
        operation_id=str(raw["operation_id"]),
        state=str(raw["state"]),
        operation_type=str(raw["operation_type"]),
        project_root=str(raw["project_root"]),
        created_at=str(raw["created_at"]),
        git_head=None if raw.get("git_head") is None else str(raw["git_head"]),
        moves=moves,
        relink=relink,
    )


def list_operations(root: Path) -> list[OperationRecord]:
    directory = project_history_dir(root)
    if not directory.is_dir():
        return []
    records: list[OperationRecord] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind") == KIND:
            records.append(_from_payload(raw))
    return records


def load_operation(root: Path, operation_id: str) -> OperationRecord:
    records = list_operations(root)
    if not records:
        raise DirecteriorError("no path-operation history for this project")
    if operation_id == "latest":
        return records[0]
    for record in records:
        if record.operation_id == operation_id:
            return record
    raise DirecteriorError(f"operation not found: {operation_id}")


def _verify(record: OperationRecord, expect_at: str) -> None:
    for move in record.moves:
        present = Path(move.destination if expect_at == "destination" else move.source)
        restored = Path(move.source if expect_at == "destination" else move.destination)
        if not present.exists():
            raise DirecteriorError(f"missing since {record.operation_type}: {present}")
        if structure_digest(present) != move.digest:
            raise DirecteriorError(f"changed since {record.operation_type}: {present}")
        if restored.exists() and not (expect_at == "destination" and move.linked_back):
            raise DirecteriorError(f"restore target already exists: {restored}")


def undo_operation(root: Path, operation_id: str, approved: bool) -> None:
    require_approval(approved, "undo")
    record = load_operation(root, operation_id)
    if record.state != "applied":
        raise DirecteriorError(f"cannot undo operation in state: {record.state}")
    _verify(record, "destination")
    for move in reversed(record.moves):
        source = Path(move.source)
        if move.linked_back:
            remove_link(source)
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(move.destination, move.source)
        if record.operation_type == "rm":
            # Only the emptied trash directory may be pruned; a managed section
            # that happens to be empty must survive.
            with suppress(OSError):
                Path(move.destination).parent.rmdir()
    # Verify before relinking: the recorded digest was taken with the offload
    # link already removed, so recreating it first would never match.
    _verify(record, "source")
    if record.relink is not None:
        link, target = record.relink
        make_link(Path(link), Path(target))
    save_operation(replace(record, state="undone"))
    print(f"undone {record.operation_type} {record.operation_id}")
    for move in record.moves:
        print(f"  restored: {move.source}")


def trash_root(hdd_root: Path, project_name: str, operation_id: str) -> Path:
    return hdd_root / TRASH_DIR / project_name / operation_id


def iter_trash(hdd_root: Path, project_name: str) -> list[Path]:
    base = hdd_root / TRASH_DIR / project_name
    if not base.is_dir():
        return []
    return sorted(path for path in base.iterdir() if path.is_dir())
