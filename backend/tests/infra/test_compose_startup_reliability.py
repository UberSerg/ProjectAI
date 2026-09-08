"""Compose topology guards for Docker Startup Reliability V1."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _find_repo_root() -> Path | None:
    for parent in [HERE, *HERE.parents]:
        candidate = parent / "docker-compose.yml"
        if candidate.is_file() and (parent / "start-kraken.ps1").is_file():
            return parent
    return None


ROOT = _find_repo_root()
COMPOSE = (ROOT / "docker-compose.yml") if ROOT else None


@pytest.fixture(scope="module")
def compose_text() -> str:
    if COMPOSE is None or not COMPOSE.is_file():
        pytest.skip("docker-compose.yml not available in this test environment")
    return COMPOSE.read_text(encoding="utf-8")


def _service_block(text: str, name: str) -> str:
    pattern = rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z0-9-]+:|\Z)"
    match = re.search(pattern, text)
    assert match, f"service missing: {name}"
    return match.group(0)


def test_compose_project_name_stable(compose_text: str) -> None:
    assert re.search(r"(?m)^name:\s*projectai\s*$", compose_text)


def test_required_services_have_restart_unless_stopped(compose_text: str) -> None:
    for name in (
        "postgres-core",
        "postgres-memory",
        "redis",
        "backend",
        "worker",
        "scheduler",
        "frontend",
    ):
        assert "restart: unless-stopped" in _service_block(compose_text, name), name


def test_infra_healthchecks_present(compose_text: str) -> None:
    for name in ("postgres-core", "postgres-memory", "redis", "backend", "worker", "frontend"):
        assert "healthcheck:" in _service_block(compose_text, name), name


def test_backend_healthcheck_uses_ready_not_only_live(compose_text: str) -> None:
    block = _service_block(compose_text, "backend")
    assert "health/ready" in block
    assert "health/live" not in block


def test_backend_depends_on_healthy_infra(compose_text: str) -> None:
    block = _service_block(compose_text, "backend")
    for name in ("postgres-core", "postgres-memory", "redis"):
        assert name in block
    assert block.count("condition: service_healthy") >= 3


def test_worker_waits_for_backend_healthy(compose_text: str) -> None:
    block = _service_block(compose_text, "worker")
    assert "backend:" in block
    assert "condition: service_healthy" in block


def test_scheduler_waits_for_backend_and_redis(compose_text: str) -> None:
    block = _service_block(compose_text, "scheduler")
    assert "redis:" in block
    assert "backend:" in block
    assert "condition: service_healthy" in block


def test_launcher_scripts_exist() -> None:
    if ROOT is None:
        pytest.skip("repo root with launchers not available")
    for name in (
        "start-kraken.cmd",
        "start-kraken.ps1",
        "stop-kraken.cmd",
        "stop-kraken.ps1",
        "status-kraken.cmd",
        "status-kraken.ps1",
        "restart-kraken.cmd",
        "restart-kraken.ps1",
    ):
        assert (ROOT / name).is_file(), name
