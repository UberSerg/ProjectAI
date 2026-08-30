# Diagnostics for Cursor / developers

ProjectAI exposes operational diagnostics over the local API so Cursor (or a developer)
can inspect the running stack without digging through Docker logs first.

## Prerequisites

```bash
docker compose up -d
```

Base URL (host): `http://localhost:8000`

## Health

```bash
curl -s http://localhost:8000/api/v1/system/health | jq
curl -s http://localhost:8000/api/v1/system/info | jq
```

## Technology events (current UTC day only)

```bash
curl -s "http://localhost:8000/api/v1/system/events?limit=50" | jq
curl -s "http://localhost:8000/api/v1/system/events?level=ERROR" | jq
curl -s "http://localhost:8000/api/v1/system/events?workflow_id=123" | jq
```

## Diagnostic report (preferred for ChatGPT / Cursor)

Plain text (ready to paste):

```bash
curl -s http://localhost:8000/api/v1/system/diagnostics/text
```

JSON wrapper:

```bash
curl -s http://localhost:8000/api/v1/system/diagnostics | jq -r .text
```

## Workflows

```bash
curl -s "http://localhost:8000/api/v1/workflows?limit=20" | jq
curl -s http://localhost:8000/api/v1/workflows/123 | jq
```

## Notes

- `system.event_logs` stores **today only** (UTC). Older rows are purged nightly and on safety cleanup.
- Daily volume is capped (`TECH_LOG_MAX_EVENTS_PER_DAY`, default 20000).
- Secrets (`password`, `token`, `api_key`, `authorization`, …) are redacted by the sanitizer.
- Frontend runtime errors are posted to `POST /api/v1/system/events/client` (non-recursive).
