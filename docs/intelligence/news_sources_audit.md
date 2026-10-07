# News / RSS / Disclosure Sources Audit (Agent D)

**Date:** 2026-10-07  
**Scope:** Kraken Intelligence Stack V1 — external event memory  
**Policy:** public feeds only; no captcha bypass; no ToS circumvention; no arbitrary URL fetch (SSRF).

## Verdict summary

| Source | Endpoint | HTTP | Adapter | known_at policy | Verdict |
|--------|----------|------|---------|-----------------|---------|
| CBR press releases | `https://www.cbr.ru/rss/RssPress` | 200 RSS | `cbr_rss` | `MAX_PUBLISHED_OBSERVED` | **READY** |
| CBR site news | `https://www.cbr.ru/rss/RssNews` | 200 RSS | `cbr_rss` | `MAX_PUBLISHED_OBSERVED` | **READY** |
| CBR events/speeches | `https://www.cbr.ru/rss/eventrss` | 200 RSS | (registry-ready) | same | **READY** (not wired; press+news sufficient) |
| MOEX ISS sitenews | `https://iss.moex.com/iss/sitenews.json` | 200 JSON | `moex_sitenews` | `MAX_PUBLISHED_OBSERVED` | **READY** |
| MOEX news RSS export | `https://www.moex.com/export/news.aspx?cat=100` | 200 RSS (~5MB) | — | — | **DEFERRED** (prefer ISS JSON; huge dump) |
| MOEX legacy rss.aspx | `https://www.moex.com/ru/news/rss.aspx` | 404 | — | — | **REJECTED** |
| e-disclosure.ru | portal / api hosts | 403 / TLS fail | — | — | **BLOCKED** (anti-bot; see dividend-disclosure spike) |
| disclosure.1prime.ru | homepage | 200 HTML | — | — | **REJECTED** (not structured feed) |
| Arbitrary user URL | n/a | n/a | — | — | **FORBIDDEN** (SSRF) |

## known_at honesty

For live allowlisted ingest:

- `published_at` = publisher claim from feed (`pubDate` / ISS `published_at`), or `null` if absent.
- `observed_at` = wall clock when Kraken fetched the artifact (UTC).
- `known_at` = `max(published_at, observed_at)` under `MAX_PUBLISHED_OBSERVED`.

Past `pubDate` does **not** create historical decision-availability. A document first seen today is not claimable as known yesterday.

MOEX ISS timestamps lack TZ; adapter attaches `Europe/Moscow (+03:00)` and records that in metadata (`published_at_tz`).

## Dedup / revision

- `document_key` = `provider|url|<canonical_url>` (fallback `provider|id|<external_id>`).
- Unique `(provider, content_hash)` → idempotent skip.
- Unique `(document_key, revision)` → content change inserts `revision+1`.

## Production wiring

Allowlist lives in `backend/app/modules/intelligence/news/registry.py`.  
Persistence: `intelligence.source_documents` (migration `20261007_0027`).  
Contract: `SourceDocumentV1`.

## Explicit non-goals (this agent)

- LLM extraction / sentiment (Agent E)
- Candidate / Shadow / Daily Decision mutations
- Scraping captcha-gated disclosure portals
- Fabricating historical news backfill timestamps
