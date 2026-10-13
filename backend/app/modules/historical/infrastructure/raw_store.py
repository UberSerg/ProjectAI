"""Durable content-addressed store for historical raw artifacts.

Bytes live on disk under a caller-supplied root, or HISTORICAL_RAW_ROOT.
The file name is the index: there is no in-memory hash list and no database row.
The repository is not a storage root.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import NamedTuple

_HASH = re.compile(r"^[0-9a-f]{64}$")
_SHARD = re.compile(r"^[0-9a-f]{2}$")
_ALGORITHM = "sha256"


class RawRootError(ValueError):
    """The raw root is missing or would write inside a git worktree."""


class RawIntegrityError(ValueError):
    """The content hash and the stored bytes do not describe the same artifact."""


class RawArtifactStat(NamedTuple):
    """Number of artifacts and the sum of their sizes in bytes."""

    count: int
    total_bytes: int


def content_hash(body: bytes) -> str:
    """Return the sha256 hex digest that addresses ``body``."""
    return _digest(body)


def resolve_raw_root(root: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the directory that may hold raw artifacts.

    An explicit root wins. Otherwise ``HISTORICAL_RAW_ROOT`` is required.
    When that variable is unset the store does not fall back to the repository.
    """
    if root is None:
        configured = os.environ.get("HISTORICAL_RAW_ROOT", "").strip()
        if not configured:
            raise RawRootError(
                "HISTORICAL_RAW_ROOT is unset; refusing to write raw artifacts into the repository"
            )
        selected = Path(configured)
    else:
        selected = Path(root)
    resolved = selected.expanduser().resolve(strict=False)
    if _is_inside_git(resolved):
        raise RawRootError(f"raw artifact root is inside a git repository: {resolved}")
    if resolved.exists() and not resolved.is_dir():
        raise RawRootError(f"raw artifact root is not a directory: {resolved}")
    return resolved


class RawArtifactStore:
    """Content-addressed files at ``<root>/sha256/<ab>/<hash>``."""

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self._root = resolve_raw_root(root)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, content_hash: str, body: bytes) -> Path:
        """Write ``body`` under its content hash. A repeat of the same bytes is a no-op."""
        digest = _normalize_hash(content_hash)
        if _digest(body) != digest:
            raise RawIntegrityError("content hash does not match body")
        path = self._path_for(digest)
        if path.is_symlink():
            raise RawIntegrityError("raw artifact path must be a regular file")
        if path.exists():
            if not path.is_file():
                raise RawIntegrityError("raw artifact path must be a regular file")
            if path.read_bytes() == body:
                return path
            raise RawIntegrityError("stored artifact bytes do not match the content hash")
        _write_atomic(path, body)
        return path

    def get(self, content_hash: str) -> bytes:
        digest = _normalize_hash(content_hash)
        path = self._path_for(digest)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(digest)
        body = path.read_bytes()
        if _digest(body) != digest:
            raise RawIntegrityError("stored artifact bytes do not match the content hash")
        return body

    def has(self, content_hash: str) -> bool:
        digest = _normalize_hash(content_hash)
        path = self._path_for(digest)
        return path.is_file() and not path.is_symlink()

    def stat(self) -> RawArtifactStat:
        """Count artifacts by file name. Sizes come from the filesystem."""
        count = 0
        total_bytes = 0
        algorithm_dir = self._root / _ALGORITHM
        if not algorithm_dir.is_dir() or algorithm_dir.is_symlink():
            return RawArtifactStat(0, 0)
        for shard in algorithm_dir.iterdir():
            if shard.is_symlink() or not shard.is_dir() or _SHARD.fullmatch(shard.name) is None:
                continue
            for artifact in shard.iterdir():
                if artifact.is_symlink() or not artifact.is_file():
                    continue
                if _HASH.fullmatch(artifact.name) is None or not artifact.name.startswith(shard.name):
                    continue
                count += 1
                total_bytes += artifact.stat().st_size
        return RawArtifactStat(count, total_bytes)

    def _path_for(self, digest: str) -> Path:
        return self._root / _ALGORITHM / digest[:2] / digest


def _digest(body: bytes) -> str:
    if not isinstance(body, bytes):
        raise TypeError("raw artifact body must be bytes")
    return hashlib.sha256(body).hexdigest()


def _normalize_hash(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("content hash must be a sha256 hex digest")
    digest = value.strip().lower()
    if _HASH.fullmatch(digest) is None:
        raise RawIntegrityError("content hash must be a sha256 hex digest")
    return digest


def _is_inside_git(path: Path) -> bool:
    """True when ``path`` is a ``.git`` directory or sits inside a worktree."""
    if any(part.lower() == ".git" for part in path.parts):
        return True
    for candidate in (path, *path.parents):
        if candidate.name.lower() == ".git":
            return True
        if (candidate / ".git").exists():
            return True
    return False


def _write_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    try:
        with temporary.open("wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
