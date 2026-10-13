"""Content-addressed raw artifact store. Bytes stay under tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.historical.infrastructure.raw_store import (
    RawArtifactStat,
    RawArtifactStore,
    RawIntegrityError,
    RawRootError,
    content_hash,
    resolve_raw_root,
)


def test_put_writes_sha256_shard_and_reads_it_back(tmp_path: Path) -> None:
    body = b"\x00raw-artifact\xff"
    digest = content_hash(body)
    store = RawArtifactStore(tmp_path)

    stored = store.put(digest, body)

    assert stored.relative_to(tmp_path).parts == ("sha256", digest[:2], digest)
    assert stored.read_bytes() == body
    assert store.get(digest) == body
    assert store.has(digest) is True
    assert store.stat() == RawArtifactStat(1, len(body))


def test_put_is_idempotent_and_a_new_instance_sees_the_file(tmp_path: Path) -> None:
    body = b"same-bytes"
    digest = content_hash(body)
    store = RawArtifactStore(tmp_path)
    first = store.put(digest, body)
    second = store.put(digest.upper(), body)

    assert second == first
    assert store.stat() == RawArtifactStat(1, len(body))

    reopened = RawArtifactStore(tmp_path)
    assert reopened.get(digest) == body
    assert reopened.stat() == RawArtifactStat(1, len(body))
    assert not hasattr(reopened, "content_hashes")


def test_stat_counts_files_and_ignores_partials(tmp_path: Path) -> None:
    store = RawArtifactStore(tmp_path / "blobs")
    assert store.stat() == RawArtifactStat(0, 0)
    assert not (tmp_path / "blobs").exists()

    first = b"alpha"
    second = b"beta-bytes"
    store.put(content_hash(first), first)
    store.put(content_hash(second), second)
    shard = content_hash(first)[:2]
    junk_dir = tmp_path / "blobs" / "sha256" / shard
    (junk_dir / ".partial").write_bytes(b"not-indexed")
    (junk_dir / "notes.txt").write_bytes(b"nope")

    assert store.stat() == RawArtifactStat(2, len(first) + len(second))

    stored = tmp_path / "blobs" / "sha256" / content_hash(first)[:2] / content_hash(first)
    stored.unlink()
    assert store.has(content_hash(first)) is False
    assert store.stat() == RawArtifactStat(1, len(second))


def test_empty_body_is_stored_once(tmp_path: Path) -> None:
    digest = content_hash(b"")
    store = RawArtifactStore(tmp_path)
    store.put(digest, b"")
    store.put(digest, b"")
    assert store.get(digest) == b""
    assert store.stat() == RawArtifactStat(1, 0)


def test_same_shard_keeps_two_files(tmp_path: Path) -> None:
    store = RawArtifactStore(tmp_path)
    by_shard: dict[str, tuple[str, bytes]] = {}
    pair: tuple[tuple[str, bytes], tuple[str, bytes]] | None = None
    for index in range(4096):
        body = f"item-{index}".encode()
        digest = content_hash(body)
        previous = by_shard.get(digest[:2])
        if previous is not None:
            pair = (previous, (digest, body))
            break
        by_shard[digest[:2]] = (digest, body)
    assert pair is not None
    for digest, body in pair:
        store.put(digest, body)
    assert store.stat() == RawArtifactStat(2, sum(len(body) for _, body in pair))
    shard = tmp_path / "sha256" / pair[0][0][:2]
    names = {path.name for path in shard.iterdir() if path.is_file() and not path.name.startswith(".")}
    assert names == {pair[0][0], pair[1][0]}


def test_missing_artifact_and_hash_mismatch_write_nothing(tmp_path: Path) -> None:
    store = RawArtifactStore(tmp_path / "outside")
    missing = content_hash(b"absent")
    assert store.has(missing) is False
    with pytest.raises(FileNotFoundError):
        store.get(missing)
    with pytest.raises(RawIntegrityError):
        store.put("ab" * 32, b"nope")
    with pytest.raises(TypeError):
        store.put(missing, "text")  # type: ignore[arg-type]
    assert not (tmp_path / "outside").exists()


def test_refuses_root_inside_a_git_directory(tmp_path: Path) -> None:
    git_dir = tmp_path / "project" / ".git"
    objects = git_dir / "objects"
    with pytest.raises(RawRootError):
        RawArtifactStore(git_dir)
    with pytest.raises(RawRootError):
        RawArtifactStore(objects)
    assert not objects.exists()


def test_refuses_root_inside_a_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    inside = repo / "data" / "raw"
    with pytest.raises(RawRootError):
        RawArtifactStore(inside)
    assert not inside.exists()

    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../repo/.git\n", encoding="utf-8")
    with pytest.raises(RawRootError):
        RawArtifactStore(worktree / "blobs")
    assert not (worktree / "blobs").exists()


def test_directory_name_containing_git_text_is_allowed(tmp_path: Path) -> None:
    root = tmp_path / "foo.gitbar"
    body = b"ok"
    store = RawArtifactStore(root)
    store.put(content_hash(body), body)
    assert store.stat().count == 1


def test_default_root_comes_from_env_and_unset_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HISTORICAL_RAW_ROOT", raising=False)
    with pytest.raises(RawRootError):
        RawArtifactStore()
    with pytest.raises(RawRootError):
        resolve_raw_root(None)
    monkeypatch.setenv("HISTORICAL_RAW_ROOT", "   ")
    with pytest.raises(RawRootError):
        RawArtifactStore()
    assert list(tmp_path.iterdir()) == []

    destination = tmp_path / "configured"
    monkeypatch.setenv("HISTORICAL_RAW_ROOT", str(destination))
    body = b"from-env"
    store = RawArtifactStore()
    store.put(content_hash(body), body)
    assert store.root == destination.resolve()
    assert store.get(content_hash(body)) == body

    blocked = tmp_path / "repo" / "blobs"
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    monkeypatch.setenv("HISTORICAL_RAW_ROOT", str(blocked))
    with pytest.raises(RawRootError):
        RawArtifactStore()
    assert not blocked.exists()


def test_explicit_root_is_not_replaced_by_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_root = tmp_path / "from-env"
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("HISTORICAL_RAW_ROOT", str(env_root))
    body = b"explicit"
    store = RawArtifactStore(explicit)
    store.put(content_hash(body), body)
    assert store.root == explicit.resolve()
    assert not env_root.exists()


def test_package_exports_the_store() -> None:
    from app.modules.historical.infrastructure import RawArtifactStore as ExportedStore

    assert ExportedStore is RawArtifactStore
