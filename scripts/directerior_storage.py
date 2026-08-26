from __future__ import annotations

import hashlib
import os
import shutil
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


def tree_snapshot(path: Path) -> TreeSnapshot:
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


def directory_size(path: Path) -> int:
    if is_offloaded(path):
        return 0
    return tree_snapshot(path).byte_count


def nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists():
        current = current.parent
    return current


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


def copy_tree_verified(source: Path, target: Path) -> TreeSnapshot:
    if target.exists():
        raise DirecteriorError(f"target already exists: {target}")
    snapshot = require_capacity(source, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    if verify_tree_copy(source, target):
        return snapshot
    shutil.rmtree(target)
    raise DirecteriorError("copy verification failed; source preserved")


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
