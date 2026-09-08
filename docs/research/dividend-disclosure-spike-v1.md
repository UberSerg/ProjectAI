# Dividend disclosure spike V1 (e-disclosure)

**Date:** 2026-09-08  
**Track:** B — free public data only  
**Verdict:** `PARTIAL_RESEARCH_ONLY`  
**Production provider implemented:** no

Artifacts: `.tmp/public-fundamentals-dividends-foundation-v1/`  
(`dividend-disclosure-coverage.json`, `dividend-provider-verdict.json`, `samples/`).

## Question

Can ProjectAI lawfully and deterministically ingest Russian equity dividend
disclosures from **e-disclosure.ru** (without login/CAPTCHA bypass, without paid
APIs) into `fundamentals.dividend_events`?

## Live access audit (2026-09-08)

| Endpoint | Status | Notes |
|---|---|---|
| `https://www.e-disclosure.ru/` | **403** | Static Forbidden bot-gateway HTML (`REQUEST-IP` / `REQUEST-ID`) |
| `https://e-disclosure.ru/` | **403** | Same gateway |
| `https://www.e-disclosure.ru/portal/company.aspx?id=…` | **403** | SBER/LKOH/TATN/MGNT/GAZP/NVTK candidates |
| `https://www.e-disclosure.ru/portal/files.aspx?id=…` | **403** | Same |
| `https://www.e-disclosure.ru/api/` | **403** | No public API body |
| `https://cfapi.e-disclosure.ru/` | TLS fail | `SSL: UNEXPECTED_EOF_WHILE_READING` |
| `https://api.e-disclosure.ru/` | TLS fail | Same |
| `https://disclosure.1prime.ru/` | **200** | Related Interfax-branded portal homepage; **not** an accepted structured dividend feed |

Sample universe: SBER, SBERP, LKOH, TATN, TATNP, MGNT, GAZP, (+ optional NVTK).  
**Dividend rows extracted from e-disclosure: 0.**

Constraints honored: no CAPTCHA/auth bypass, no paid APIs, no fabricated dates.

### Access model

e-disclosure.ru currently behaves as an **anti-bot auth gateway** for automated
clients: HTTP 403 Forbidden with a support-report page. This is **not** free
machine-readable public HTML/API access for ingest.

A browser may still work for a human operator; that does **not** authorize
automation or challenge bypass. Commercial/subscription disclosure APIs exist
elsewhere — out of scope for this free-data spike.

**Conclusion:** access model = **gated / not lawfully automatable in this
environment**. Parser feasibility cannot be proven on live bodies.

## Deterministic parser (no LLM)

| Condition | Status |
|---|---|
| Stable public HTML/JSON with dividend fields | **Not observed** (403) |
| Fixture-driven deterministic parser | **Blocked** until lawful payloads exist |
| LLM extraction | **Rejected** for the core ingest path |

If a lawful feed appears later, a deterministic parser is the only acceptable
path: fixed field map, versioned fixtures, reject ambiguous rows. Do not use
Polza/LLM as calculator or source of dates/amounts.

## Recommendation vs approval

Dividend lifecycle must keep stages separate (already reflected in schema /
`DividendStatus`):

| Stage | Meaning | Typical status |
|---|---|---|
| Board recommendation | Issuer board proposes amount / dates | `RECOMMENDED` |
| Shareholder / AGM approval | Corporate action authorized | `APPROVED` |
| Paid / settled | Cash actually paid (if known) | `PAID` |
| Cancelled / changed | Superseding disclosure | `CANCELLED` + new version |

**Never collapse recommendation into approval.** A recommended dividend is not
an approved entitlement. Amounts and dates may change between versions;
`version` / `supersedes_id` preserve history. PIT visibility uses `known_at`
(disclosure availability), not the economic `record_date`.

## SBER ≠ SBERP (and TATN ≠ TATNP)

Common and preferred shares are **different instruments** (different SECID,
ISIN, often different DPS).

- Identity: MOEX ISS `SECID` / `ISIN` / emitent fields (identity layer works in
  this probe).
- Storage: `instrument_id` on `fundamentals.dividend_events` must point at the
  correct share class.
- Issuer-level disclosures that name “обыкновенные / привилегированные” must be
  mapped explicitly; if the share class is ambiguous → **reject / skip**, do not
  guess.
- Prefer mapping tables keyed by ISIN when the disclosure cites ISIN; never copy
  SBER DPS onto SBERP because “same bank”.

## `published_at` / `known_at` preservation

- `known_at` is mandatory for ingest (`MISSING_KNOWN_AT` → skip).
- Prefer disclosure **publication timestamp/date** from the source document
  (`published_at` when available) as the availability clock.
- Do **not** backdate `known_at` to `record_date`, `ex_date`, or `payment_date`.
- Do **not** invent publication dates from “today” for historical backfill.
- If only a PDF without a trustworthy publication clock exists → leave for a
  later stage; do not invent.

## Ex-date policy (do not fabricate)

**Forbidden:** `ex_date = record_date - 1` calendar day as a hardcoded rule.

MOEX equity settlement moved from **T+2 to T+1** effective **2023-07-31**.
Ex-date relative to record (registry) date therefore depends on:

1. the settlement cycle in force on that calendar day;
2. the **trading calendar** (weekends / non-trading days), not civil calendar
   subtraction alone.

For V1:

- Store `record_date` when disclosed.
- Store `ex_date` **only** when explicitly present in the source **or** when a
  future, versioned settlement helper derives it with provenance
  (`settlement_cycle`, `calendar_id`, rule version) and tests.
- Until that helper exists and is accepted: leave `ex_date` null rather than
  fabricating it.
- Gross total-return attribution that requires `ex_date` must stay
  `PARTIAL` / `NOT_READY` when ex-dates are missing — honest coverage.

## IR fallback (`RESEARCH_FALLBACK`)

Probe of ~3 issuer IR hubs (SBER, LKOH, GAZP):

- Paths/hosts are unstable (TLS/certificate failures, 404s).
- Even when HTML loads, schemas are issuer-specific and lack a uniform
  `published_at` contract.

**Role:** `RESEARCH_FALLBACK` only — optional manual/research cross-check for a
handful of issuers. **Not** production coverage, **not** universe-wide ingest,
unless a later audit shows unusually stable structured IR feeds (not observed
here).

## Corporate events foundation (types only as needed)

Dividend disclosures belong in `fundamentals.dividend_events`, not as candle
repairs. Related corporate-event foundation types for later wiring (see
`docs/architecture/corporate-events-foundation-v1.md`):

- Keep mechanical CA (`SPLIT` / `REVERSE_SPLIT`) separate from cash dividends.
- Do not invent `DIVIDEND` corporate_events rows from empty probes.
- Entitlement for total-return research is a **downstream consumer** of
  approved dividend events — not the disclosure itself.

## Recommendation

1. **Do not** implement `EDisclosureDividendProvider` while access remains 403.
2. Keep `get_dividend_provider()` / ingest on the honest `NOT_READY` /
   `DEFERRED` path.
3. Use this spike’s docs + JSON as the readiness gate for a future lawful feed
   (official API / licensed dump / stable public JSON).
4. When a feed appears, implement a **bounded** deterministic provider against
   existing `DividendProvider` / `dividend_events` — still no Dataset V2/V3
   mutation without a version bump.

## Related

- ADR 0005 — raw market / corporate actions / returns
- ADR 0010 — gross total return foundation
- ADR 0014 — dividend lifecycle separate from TR entitlement
- `docs/architecture/corporate-events-foundation-v1.md`
- `docs/research/dividend-pit-readiness-v1.md`
