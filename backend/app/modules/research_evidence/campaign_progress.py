"""Operational live progress for Canonical Evidence Campaign V1.

Approximate weighted progress. Not part of campaign evidence identity.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Frozen before this run's investment results. Do not re-weight after observation.
STAGE_WEIGHTS: dict[str, float] = {
    "DATA_SNAPSHOT": 1.0,
    "SAFE_DATA_REFRESH": 1.0,
    "BUILD_V3": 3.0,
    "BUILD_V4": 25.0,
    "FAIR_PAIR_PROOF": 2.0,
    "OOS_REGRESSION": 8.0,
    "OOS_RANKER": 10.0,
    "ABLATION": 20.0,
    "STABILITY": 3.0,
    "ECONOMICS_PRIMARY": 5.0,
    "ECONOMICS_ROBUSTNESS": 15.0,
    "PROSPECTIVE_SNAPSHOT": 2.0,
    "DOSSIER": 3.0,
    "FINALIZE": 2.0,
}

STAGE_LABELS: dict[str, str] = {
    "DATA_SNAPSHOT": "Data snapshot",
    "SAFE_DATA_REFRESH": "Safe refresh",
    "BUILD_V3": "Dataset V3 reuse",
    "BUILD_V4": "Dataset V4",
    "FAIR_PAIR_PROOF": "Fair V3/V4 pair",
    "OOS_REGRESSION": "OOS regression",
    "OOS_RANKER": "OOS ranker",
    "ABLATION": "Feature ablation",
    "STABILITY": "Stability slices",
    "ECONOMICS_PRIMARY": "Primary economics",
    "ECONOMICS_ROBUSTNESS": "Economics robustness",
    "PROSPECTIVE_SNAPSHOT": "Prospective snapshot",
    "DOSSIER": "Evidence dossier",
    "FINALIZE": "Finalize",
}

HEARTBEAT_FILE_SECONDS = 45.0
HEARTBEAT_CONSOLE_SECONDS = 180.0
PROGRESS_FILENAME = "progress.json"

ProgressCallback = Callable[[dict[str, Any]], None]


def assert_weights_sum_100() -> None:
    total = sum(STAGE_WEIGHTS.values())
    if abs(total - 100.0) > 1e-9:
        raise AssertionError(f"progress weights must sum to 100, got {total}")


def format_hms(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:
        return "--:--:--"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def eta_quality(pct: float) -> str:
    if pct < 10:
        return "LOW"
    if pct < 50:
        return "MEDIUM"
    return "HIGH"


def write_progress_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class CampaignProgress:
    """Monotonic approximate campaign progress + heartbeat (operational only)."""

    def __init__(
        self,
        path: Path,
        *,
        campaign_id: str,
        campaign_fingerprint: str | None = None,
        heartbeat: bool = True,
    ) -> None:
        assert_weights_sum_100()
        self.path = path
        self.campaign_id = campaign_id
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._status = "RUNNING"
        self._stage = "PRECHECK"
        self._max_pct = 0.0
        self._completed: list[str] = []
        self._intra: dict[str, float] = {}
        self._stage_progress: dict[str, Any] | None = None
        self._message = "starting"
        self._fingerprint = campaign_fingerprint
        self._block_code: str | None = None
        self._block_reason: str | None = None
        self._error: str | None = None
        self._last_console_beat = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_file_write = 0.0
        if heartbeat:
            self._thread = threading.Thread(target=self._heartbeat_loop, name="campaign-progress", daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._flush(force=True)

    def mark_completed(self, stages: list[str]) -> None:
        with self._lock:
            for name in stages:
                if name in STAGE_WEIGHTS and name not in self._completed:
                    self._completed.append(name)
                    self._intra[name] = 1.0
            self._recompute_locked("resume from completed stages")
            self._flush_locked(force=True)

    def set_fingerprint(self, fingerprint: str | None) -> None:
        with self._lock:
            self._fingerprint = fingerprint
            self._flush_locked(force=True)

    def set_stage(self, stage: str, *, message: str | None = None) -> None:
        with self._lock:
            self._stage = stage
            if message:
                self._message = message
            self._recompute_locked(self._message)
            self._flush_locked(force=True)
            self._console_locked()

    def complete_stage(self, stage: str) -> None:
        with self._lock:
            if stage in STAGE_WEIGHTS and stage not in self._completed:
                self._completed.append(stage)
            self._intra[stage] = 1.0
            self._stage = stage
            self._recompute_locked(f"{stage} complete")
            self._flush_locked(force=True)
            self._console_locked()

    def update_stage_units(
        self,
        stage: str,
        *,
        current: int,
        total: int,
        unit: str,
        message: str | None = None,
    ) -> None:
        with self._lock:
            self._stage = stage
            frac = 0.0 if total <= 0 else min(1.0, max(0.0, current / total))
            prev = self._intra.get(stage, 0.0)
            self._intra[stage] = max(prev, frac)
            self._stage_progress = {
                "current": current,
                "total": total,
                "pct": round(100.0 * self._intra[stage], 2),
                "unit": unit,
            }
            self._message = message or f"{STAGE_LABELS.get(stage, stage)} {current}/{total} {unit}"
            self._recompute_locked(self._message)
            self._flush_locked(force=True)
            self._console_locked()

    def finish(
        self,
        *,
        status: str,
        block_code: str | None = None,
        block_reason: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._status = status
            self._block_code = block_code
            self._block_reason = block_reason
            self._error = error
            if status == "COMPLETE":
                for name in STAGE_WEIGHTS:
                    if name not in self._completed:
                        self._completed.append(name)
                    self._intra[name] = 1.0
                self._max_pct = 100.0
                self._message = "campaign complete"
            elif status == "BLOCKED":
                self._message = block_reason or block_code or "blocked"
            else:
                self._message = error or "error"
            self._recompute_locked(self._message)
            if status == "COMPLETE":
                self._max_pct = 100.0
            self._flush_locked(force=True)
            self._console_locked()
        self.close()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._payload_locked())

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_FILE_SECONDS):
            with self._lock:
                if self._status != "RUNNING":
                    return
                now = time.monotonic()
                self._flush_locked(force=True)
                if now - self._last_console_beat >= HEARTBEAT_CONSOLE_SECONDS:
                    self._last_console_beat = now
                    pct = self._max_pct
                    elapsed = format_hms(now - self._started)
                    print(
                        f"[HEARTBEAT] {self._stage} alive | ≈{pct:.1f}% | elapsed {elapsed}",
                        flush=True,
                    )

    def _recompute_locked(self, message: str) -> None:
        pct = 0.0
        for name, weight in STAGE_WEIGHTS.items():
            frac = 1.0 if name in self._completed else self._intra.get(name, 0.0)
            pct += weight * max(0.0, min(1.0, frac))
        pct = min(100.0, max(self._max_pct, pct))
        self._max_pct = pct
        self._message = message

    def _payload_locked(self) -> dict[str, Any]:
        elapsed = time.monotonic() - self._started
        pct = self._max_pct
        remaining = max(0.0, 100.0 - pct)
        eta = None
        quality = "LOW"
        if pct >= 10.0:
            eta = elapsed / (pct / 100.0) * (remaining / 100.0) if pct > 0 else None
            quality = eta_quality(pct)
        payload: dict[str, Any] = {
            "campaign_id": self.campaign_id,
            "campaign_fingerprint": self._fingerprint,
            "status": self._status,
            "stage": self._stage,
            "stage_label": STAGE_LABELS.get(self._stage, self._stage),
            "approx_progress_pct": round(pct, 1),
            "stage_progress": self._stage_progress,
            "completed_stages": list(self._completed),
            "elapsed_seconds": int(elapsed),
            "rough_eta_seconds": None if eta is None else int(eta),
            "rough_eta_quality": quality,
            "last_progress_at": datetime.now(UTC).isoformat(),
            "message": self._message,
            "progress_is_approximate": True,
        }
        if self._block_code:
            payload["block_code"] = self._block_code
            payload["block_reason"] = self._block_reason
        if self._error:
            payload["error"] = self._error
        return payload

    def _flush(self, *, force: bool) -> None:
        with self._lock:
            self._flush_locked(force=force)

    def _flush_locked(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_file_write < 1.0:
            return
        write_progress_atomic(self.path, self._payload_locked())
        self._last_file_write = now

    def _console_locked(self) -> None:
        payload = self._payload_locked()
        sp = payload.get("stage_progress") or {}
        units = ""
        if sp.get("current") is not None and sp.get("total") is not None:
            units = f" | {sp['current']}/{sp['total']} {sp.get('unit') or ''}".rstrip()
        eta = payload.get("rough_eta_seconds")
        eta_txt = f" | ETA ~{format_hms(eta)}" if eta is not None else ""
        print(
            f"[PROGRESS] ≈{payload['approx_progress_pct']:.1f}% | {payload['stage']}{units} "
            f"| elapsed {format_hms(payload['elapsed_seconds'])}{eta_txt}",
            flush=True,
        )
        self._last_console_beat = time.monotonic()


def mark_progress_file_error(path: Path, *, error: str) -> None:
    """Operational ERROR stamp if the process dies after progress.json exists."""
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("status") in {"COMPLETE", "BLOCKED"}:
        return
    payload["status"] = "ERROR"
    payload["error"] = error[:800]
    payload["message"] = error[:800]
    payload["last_progress_at"] = datetime.now(UTC).isoformat()
    write_progress_atomic(path, payload)


def wrap_step_hook(
    progress: CampaignProgress,
    inner: Callable[[str, str, str | None], None] | None,
) -> Callable[[str, str, str | None], None]:
    def _hook(name: str, status: str, error: str | None = None) -> None:
        if status in {"SUCCESS", "SKIPPED_RESUME"}:
            progress.complete_stage(name)
        elif status == "RUNNING":
            progress.set_stage(name, message=f"{name} running")
        elif status in {"WARNING", "BLOCKED", "ERROR"}:
            # BLOCKED historical stages emit WARNING; do not treat as complete work.
            progress.set_stage(name, message=error or status)
        if inner is not None:
            inner(name, status, error)

    return _hook


__all__ = [
    "PROGRESS_FILENAME",
    "STAGE_LABELS",
    "STAGE_WEIGHTS",
    "CampaignProgress",
    "assert_weights_sum_100",
    "format_hms",
    "wrap_step_hook",
    "write_progress_atomic",
    "mark_progress_file_error",
]
