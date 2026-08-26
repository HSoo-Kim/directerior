from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from directerior_core import DirecteriorError
from directerior_storage import TreeSnapshot

MIGRATION_KIND = "migration"


@dataclass(frozen=True, slots=True)
class LeafMigration:
    names: tuple[str, ...]
    leaf_relative: str
    code_existed: bool
    results_existed: bool
    offloaded: bool
    code_snapshot: TreeSnapshot
    results_snapshot: TreeSnapshot
    plan_snapshot: TreeSnapshot | None
    old_hdd_target: str
    new_hdd_target: str


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    operation_id: str
    state: str
    project_root: str
    created_at: str
    before_config: bytes
    after_config: bytes
    leaves: tuple[LeafMigration, ...]
    operation_type: str = "migrate_layout"
    parent_id: str | None = None
    before_fingerprint: str = ""
    after_fingerprint: str = ""


def state_home() -> Path:
    override = os.environ.get("DIRECTERIOR_STATE_HOME")
    if override is not None:
        return Path(override)
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local is not None:
            return Path(local) / "directerior"
    xdg = os.environ.get("XDG_STATE_HOME")
    return (
        Path(xdg) / "directerior"
        if xdg is not None
        else Path.home() / ".local/state/directerior"
    )


def project_history_dir(root: Path) -> Path:
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:20]
    return state_home() / "history" / key


def new_operation_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _snapshot(raw: dict[str, str | int]) -> TreeSnapshot:
    return TreeSnapshot(
        file_count=int(raw["file_count"]),
        byte_count=int(raw["byte_count"]),
        digest=str(raw["digest"]),
    )


def compute_fingerprint(
    record: MigrationRecord,
    side: Literal["before", "after"],
) -> str:
    if side == "after" and any(leaf.plan_snapshot is None for leaf in record.leaves):
        return ""
    leaves = []
    for leaf in sorted(record.leaves, key=lambda item: item.leaf_relative):
        payload = {
            "names": leaf.names,
            "leaf_relative": leaf.leaf_relative,
            "code_existed": leaf.code_existed,
            "results_existed": leaf.results_existed,
            "offloaded": leaf.offloaded,
            "code_snapshot": asdict(leaf.code_snapshot),
            "results_snapshot": asdict(leaf.results_snapshot),
            "hdd_target": (
                leaf.old_hdd_target if side == "before" else leaf.new_hdd_target
            ),
        }
        if side == "after":
            plan_snapshot = leaf.plan_snapshot
            if plan_snapshot is None:
                raise DirecteriorError("after fingerprint requires plan snapshot")
            payload["plan_snapshot"] = asdict(plan_snapshot)
        leaves.append(payload)
    canonical = {
        "config_sha256": hashlib.sha256(
            record.before_config if side == "before" else record.after_config
        ).hexdigest(),
        "leaves": leaves,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def find_parent_id(records: list[MigrationRecord], before_fingerprint: str) -> str | None:
    for record in records:
        if record.state == "applied" and record.after_fingerprint == before_fingerprint:
            return record.operation_id
    return None


def save_record(record: MigrationRecord) -> None:
    directory = project_history_dir(Path(record.project_root))
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 2,
        "kind": MIGRATION_KIND,
        "id": record.operation_id,
        "state": record.state,
        "project_root": record.project_root,
        "created_at": record.created_at,
        "before_config_b64": base64.b64encode(record.before_config).decode("ascii"),
        "after_config_b64": base64.b64encode(record.after_config).decode("ascii"),
        "operation_type": record.operation_type,
        "parent_id": record.parent_id,
        "before_fingerprint": record.before_fingerprint,
        "after_fingerprint": record.after_fingerprint,
        "leaves": [asdict(leaf) for leaf in record.leaves],
    }
    target = directory / f"{record.operation_id}.json"
    staging = target.with_suffix(".json.tmp")
    staging.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    staging.replace(target)


def load_record(root: Path, operation_id: str) -> MigrationRecord:
    records = list_records(root)
    if not records:
        raise DirecteriorError("no migration history for this project")
    if operation_id == "latest":
        return records[0]
    for record in records:
        if record.operation_id == operation_id:
            return record
    raise DirecteriorError(f"migration history not found: {operation_id}")


def record_kind(root: Path, operation_id: str) -> str:
    """Which journal owns an id: migrations or path operations."""
    directory = project_history_dir(root)
    entries = sorted(directory.glob("*.json"), reverse=True) if directory.is_dir() else []
    for path in entries:
        raw = json.loads(path.read_text(encoding="utf-8"))
        kind = str(raw.get("kind", MIGRATION_KIND))
        if operation_id == "latest" or raw["id"] == operation_id:
            return kind
    raise DirecteriorError(f"no history entry for: {operation_id}")


def list_records(root: Path) -> list[MigrationRecord]:
    directory = project_history_dir(root)
    if not directory.is_dir():
        return []
    records: list[MigrationRecord] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("kind", MIGRATION_KIND) != MIGRATION_KIND:
            continue
        leaves = tuple(
            LeafMigration(
                names=tuple(leaf["names"]),
                leaf_relative=leaf["leaf_relative"],
                code_existed=leaf["code_existed"],
                results_existed=leaf["results_existed"],
                offloaded=leaf["offloaded"],
                code_snapshot=_snapshot(leaf["code_snapshot"]),
                results_snapshot=_snapshot(leaf["results_snapshot"]),
                plan_snapshot=(
                    _snapshot(leaf["plan_snapshot"])
                    if leaf["plan_snapshot"] is not None
                    else None
                ),
                old_hdd_target=leaf["old_hdd_target"],
                new_hdd_target=leaf["new_hdd_target"],
            )
            for leaf in raw["leaves"]
        )
        record = MigrationRecord(
            operation_id=raw["id"],
            state=raw["state"],
            project_root=raw["project_root"],
            created_at=raw["created_at"],
            before_config=base64.b64decode(raw["before_config_b64"]),
            after_config=base64.b64decode(raw["after_config_b64"]),
            leaves=leaves,
            operation_type=raw.get("operation_type", "migrate_layout"),
            parent_id=raw.get("parent_id"),
            before_fingerprint=raw.get("before_fingerprint", ""),
            after_fingerprint=raw.get("after_fingerprint", ""),
        )
        if not record.before_fingerprint:
            record = replace_record_fingerprints(record)
        records.append(record)
    return records


def replace_record_fingerprints(record: MigrationRecord) -> MigrationRecord:
    from dataclasses import replace

    return replace(
        record,
        before_fingerprint=compute_fingerprint(record, "before"),
        after_fingerprint=compute_fingerprint(record, "after"),
    )


def show_history(root: Path, as_json: bool) -> None:
    from directerior_ops import list_operations

    entries = [
        {
            "id": record.operation_id,
            "kind": MIGRATION_KIND,
            "state": record.state,
            "created_at": record.created_at,
            "operation_type": record.operation_type,
            "parent_id": record.parent_id,
            "before_fingerprint": record.before_fingerprint,
            "after_fingerprint": record.after_fingerprint,
        }
        for record in list_records(root)
    ]
    entries.extend(
        {
            "id": record.operation_id,
            "kind": "path_op",
            "state": record.state,
            "created_at": record.created_at,
            "operation_type": record.operation_type,
            "git_head": record.git_head,
            "paths": [move.source for move in record.moves],
        }
        for record in list_operations(root)
    )
    entries.sort(key=lambda entry: str(entry["id"]), reverse=True)
    if as_json:
        print(json.dumps({"entries": entries}))
        return
    for entry in entries:
        if entry["kind"] == MIGRATION_KIND:
            parent = entry["parent_id"] or "ROOT"
            print(
                f"{parent} -> {entry['id']}  {entry['operation_type']}  "
                f"{entry['state']}  {str(entry['before_fingerprint'])[:8]}"
                f"->{str(entry['after_fingerprint'])[:8]}"
            )
        else:
            paths = ", ".join(str(path) for path in entry["paths"])  # pyright: ignore[reportGeneralTypeIssues]
            print(f"{entry['id']}  {entry['operation_type']}  {entry['state']}  {paths}")
