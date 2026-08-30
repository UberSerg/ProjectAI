"""Raw market payload storage on filesystem volume."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class RawStore:
    def __init__(self, root: str | None = None) -> None:
        settings = get_settings()
        self.root = Path(root or settings.raw_data_path)

    def save(
        self,
        *,
        source: str,
        data_type: str,
        batch_id: int | str,
        name: str,
        payload: str | bytes | dict[str, Any],
        content_type: str = "application/json",
    ) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        directory = self.root / source.lower() / data_type / day / str(batch_id)
        directory.mkdir(parents=True, exist_ok=True)
        suffix = ".json" if "json" in content_type else ".xml" if "xml" in content_type else ".txt"
        path = directory / f"{name}{suffix}"
        if isinstance(payload, dict):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        elif isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(payload, encoding="utf-8")
        return str(path)
