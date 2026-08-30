from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from directerior_core import DirecteriorError


@dataclass(frozen=True, slots=True)
class TreeSnapshot:
    file_count: int
    byte_count: int
    digest: str


def is_offloaded(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            return bool(getattr(os.lstat(path), "st_reparse_tag", 0))
        except OSError:
            return False
    return False

def link_target(path: Path) -> Path | None:
    """Return a link or junction target without treating ordinary paths as links."""
    if not is_offloaded(path):
        return None
    try:
        if path.is_symlink():
            target = Path(os.readlink(path))
            if not target.is_absolute():
                target = path.parent / target
            return target.resolve(strict=False)
        return path.resolve(strict=False)
    except OSError:
        return None


def tree_snapshot(path: Path) -> TreeSnapshot:
    require_plain_tree(path, "snapshot")
    digest = hashlib.sha256()
    file_count = 0
    byte_count = 0
    for directory, subdirs, filenames in os.walk(path):
        subdirs.sort()
        for subdir in subdirs:
            directory_path = Path(directory) / subdir
            relative_directory = directory_path.relative_to(path).as_posix()
            digest.update(b"D\0")
            digest.update(relative_directory.encode("utf-8"))
        for filename in sorted(filenames):
            file_path = Path(directory) / filename
            relative = file_path.relative_to(path).as_posix()
            digest.update(b"F\0")
            digest.update(relative.encode("utf-8"))
            size = file_path.stat().st_size
            digest.update(str(size).encode("ascii"))
            with file_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            file_count += 1
            byte_count += size
    return TreeSnapshot(file_count=file_count, byte_count=byte_count, digest=digest.hexdigest())


def _entry_is_link(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_symlink() or bool(
            getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0)
        )
    except OSError:
        return True


def tree_snapshot_no_follow(path: Path, exclude: Path | None = None) -> TreeSnapshot:
    digest = hashlib.sha256()
    file_count = 0
    byte_count = 0
    pending = [path]
    while pending:
        current = pending.pop()
        entries = sorted(os.scandir(current), key=lambda entry: entry.name, reverse=True)
        for entry in entries:
            entry_path = Path(entry.path)
            if exclude is not None and entry_path == exclude:
                continue
            relative = entry_path.relative_to(path).as_posix()
            if _entry_is_link(entry):
                digest.update(b"L\0")
                digest.update(relative.encode("utf-8"))
                target = link_target(entry_path)
                digest.update(str(target).encode("utf-8") if target is not None else b"?")
            elif entry.is_dir(follow_symlinks=False):
                digest.update(b"D\0")
                digest.update(relative.encode("utf-8"))
                pending.append(entry_path)
            elif entry.is_file(follow_symlinks=False):
                digest.update(b"F\0")
                digest.update(relative.encode("utf-8"))
                size = entry.stat(follow_symlinks=False).st_size
                digest.update(str(size).encode("ascii"))
                with entry_path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                file_count += 1
                byte_count += size
    return TreeSnapshot(file_count=file_count, byte_count=byte_count, digest=digest.hexdigest())

def directory_size(path: Path) -> int:
    if is_offloaded(path):
        return 0
    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            entries = os.scandir(current)
        except OSError:
            continue
        with entries:
            for entry in entries:
                if _entry_is_link(entry):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total


def require_plain_tree(path: Path, operation: str) -> None:
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            entries = os.scandir(current)
        except OSError as exc:
            raise DirecteriorError(f"{operation} cannot scan source tree: {current}") from exc
        with entries:
            for entry in entries:
                entry_path = Path(entry.path)
                if _entry_is_link(entry):
                    raise DirecteriorError(
                        f"{operation} refuses nested link/reparse point: {entry_path}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(entry_path)


def nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists():
        current = current.parent
    return current

def _resolved_path(path: Path) -> Path:
    existing = nearest_existing(path)
    suffix = path.relative_to(existing)
    return existing.resolve() / suffix


def require_disjoint_paths(source: Path, target: Path, operation: str) -> None:
    resolved_source = _resolved_path(source)
    resolved_target = _resolved_path(target)
    if (
        resolved_source == resolved_target
        or resolved_source in resolved_target.parents
        or resolved_target in resolved_source.parents
    ):
        raise DirecteriorError(
            f"{operation} requires disjoint source and target paths: "
            f"{source} and {target}"
        )


def same_volume(source: Path, target: Path) -> bool:
    target_existing = nearest_existing(target)
    if os.name == "nt":
        return source.resolve().drive.casefold() == target_existing.resolve().drive.casefold()
    return source.stat().st_dev == target_existing.stat().st_dev


def require_capacity(source: Path, target: Path) -> TreeSnapshot:
    snapshot = tree_snapshot(source)
    free = shutil.disk_usage(nearest_existing(target)).free
    if free < snapshot.byte_count:
        raise DirecteriorError(
            f"insufficient free space: need {snapshot.byte_count} bytes, have {free} bytes"
        )
    return snapshot


def verify_tree_copy(source: Path, target: Path) -> bool:
    return tree_snapshot(source) == tree_snapshot(target)


def copy_tree_verified(
    source: Path, target: Path, operation: str = "copy"
) -> TreeSnapshot:
    if target.exists() or is_offloaded(target):
        raise DirecteriorError(f"target already exists: {target}")
    require_plain_tree(source, operation)
    require_disjoint_paths(source, target, operation)
    snapshot = require_capacity(source, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, target)
        if verify_tree_copy(source, target):
            return snapshot
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise
    shutil.rmtree(target)
    raise DirecteriorError("copy verification failed; source preserved")


def file_snapshot(path: Path) -> TreeSnapshot:
    digest = hashlib.sha256()
    size = path.stat().st_size
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return TreeSnapshot(file_count=1, byte_count=size, digest=digest.hexdigest())


def copy_file_verified(
    source: Path, target: Path, operation: str = "copy"
) -> TreeSnapshot:
    if target.exists() or is_offloaded(target):
        raise DirecteriorError(f"target already exists: {target}")
    require_disjoint_paths(source, target, operation)
    snapshot = file_snapshot(source)
    free = shutil.disk_usage(nearest_existing(target)).free
    if free < snapshot.byte_count:
        raise DirecteriorError(
            f"insufficient free space: need {snapshot.byte_count} bytes, have {free} bytes"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, staging)
        if file_snapshot(staging) != snapshot:
            raise DirecteriorError("copy verification failed; source preserved")
        staging.replace(target)
        return snapshot
    finally:
        if staging.exists():
            staging.unlink()


def make_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def remove_link(link: Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        os.rmdir(link)
