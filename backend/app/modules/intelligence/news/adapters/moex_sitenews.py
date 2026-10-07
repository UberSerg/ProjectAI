"""MOEX ISS sitenews JSON adapter (public structured feed)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from app.modules.intelligence.news.adapters.base import AdapterResult, FetchedDocument
from app.modules.intelligence.news.hashing import canonical_url, content_hash, document_key
from app.modules.intelligence.news.http import NewsHttpClient
from app.modules.intelligence.news.known_at import compute_known_at
from app.modules.intelligence.news.registry import SourceDefinition

# MOEX ISS sitenews timestamps are Moscow wall-clock without offset.
_MSK = timezone(timedelta(hours=3), name="Europe/Moscow")


class MoexSitenewsAdapter:
    def fetch(self, source: SourceDefinition, client: NewsHttpClient) -> AdapterResult:
        observed_at = datetime.now(UTC)
        query = urlencode({"limit": source.max_items, "iss.meta": "off"})
        url = f"{source.feed_url}?{query}"
        payload = client.fetch_bytes(source, url=url)
        warnings: list[str] = []
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return AdapterResult(
                documents=(),
                warnings=(f"malformed_json:{exc}",),
                fetched_bytes=len(payload),
            )

        block = data.get("sitenews") if isinstance(data, dict) else None
        if not isinstance(block, dict):
            return AdapterResult(
                documents=(),
                warnings=("missing_sitenews_block",),
                fetched_bytes=len(payload),
            )
        columns = block.get("columns") or []
        rows = block.get("data") or []
        if not isinstance(columns, list) or not isinstance(rows, list):
            return AdapterResult(
                documents=(),
                warnings=("malformed_sitenews_shape",),
                fetched_bytes=len(payload),
            )

        docs: list[FetchedDocument] = []
        for idx, row in enumerate(rows[: source.max_items]):
            try:
                docs.append(self._row_to_doc(source, columns, row, observed_at))
            except Exception as exc:  # noqa: BLE001 — isolate bad rows
                warnings.append(f"row_{idx}:{type(exc).__name__}:{exc}")
        return AdapterResult(
            documents=tuple(docs),
            warnings=tuple(warnings),
            fetched_bytes=len(payload),
        )

    def _row_to_doc(
        self,
        source: SourceDefinition,
        columns: list[Any],
        row: Any,
        observed_at: datetime,
    ) -> FetchedDocument:
        if not isinstance(row, list):
            raise ValueError("row_not_list")
        record = {str(columns[i]): row[i] for i in range(min(len(columns), len(row)))}
        news_id = record.get("id")
        if news_id is None:
            raise ValueError("missing_id")
        ext = str(news_id)
        title = str(record.get("title") or "").strip() or None
        published_at = _parse_moex_dt(record.get("published_at"))
        modified_at = _parse_moex_dt(record.get("modified_at"))
        # Canonical public news page on moex.com (stable by id).
        url = canonical_url(f"https://www.moex.com/n{ext}")
        body = title or ""
        digest = content_hash(title=title, body=body, canonical=url)
        known_at, known_basis = compute_known_at(
            policy=source.known_at_policy,
            published_at=published_at,
            observed_at=observed_at,
        )
        key = document_key(provider=source.provider, canonical=url, external_id=ext)
        return FetchedDocument(
            document_key=key,
            provider=source.provider,
            source_type=source.source_type,
            canonical_url=url,
            title=title,
            published_at=published_at,
            observed_at=observed_at,
            known_at=known_at,
            content_hash=digest,
            language=source.language,
            raw_text=body,
            external_id=ext,
            metadata={
                "source_id": source.source_id,
                "adapter": source.adapter,
                "feed_url": source.feed_url,
                "known_at_basis": known_basis,
                "known_at_policy": source.known_at_policy,
                "tag": record.get("tag"),
                "modified_at": modified_at.isoformat() if modified_at else None,
                "published_at_tz": "Europe/Moscow(+03:00)",
            },
        )


def _parse_moex_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        naive = datetime.fromisoformat(text)
    except ValueError:
        return None
    if naive.tzinfo is None:
        return naive.replace(tzinfo=_MSK).astimezone(UTC)
    return naive.astimezone(UTC)
