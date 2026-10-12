# Bank / FI Fundamentals — Free Sources Audit (Intelligence Stack V1)

**Agent:** C (`agent/intel-c-banks`)  
**Audit date:** 2026-10-07  
**Foundation:** `8e15a3c` Intelligence Stack V1 contracts  
**Principle:** Unknown > fabricated. Missing ≠ zero. No captcha bypass. No paid feeds.

## 1. Non-negotiable rule (preserved)

Bank / financial-institution industrial FNS RAS features are **unsupported**.

| Control | Location | Status |
|---|---|---|
| Hard-deny SECID set | `BANK_FI_SECIDS` in `fns_gir_bo_provider.py` | preserved |
| FNS identity shortcut | `BANK_FI_NOT_SUPPORTED_BY_FNS_RAS_V1` | preserved |
| Dataset V4 lineage | `UNSUPPORTED_BANK_FI` / `BANK_FI_SEMANTICS_UNSUPPORTED` | preserved |
| Knowledge rule | `bank_industrial_ratios_forbidden` | preserved |
| Intelligence banks module | never falls back to industrial ratios | **new** |

SECIDs: `SBER`, `SBERP`, `VTBR`, `BSPB`, `CBOM`.

Live re-check 2026-10-07: FNS GIR BO search for SBER INN `7707083893` → `totalElements=0`.

## 2. Executive verdict

| Layer | Verdict | Programmatic? |
|---|---|---|
| Universe-wide bank fundamentals feed | **NOT_AVAILABLE** | — |
| Bank fundamentals intelligence layer | **PARTIAL** | coverage/identity only |
| Industrial FNS for banks | **NOT_AVAILABLE** (forbidden) | JSON exists for industrials only |
| SBER honest semantics | **BANK_FI + PARTIAL/UNKNOWN metrics** | no fake industrial ratios |

**Overall provider status for Intelligence Stack V1:** `PARTIAL`  
(Reason: CreditOrgInfo SOAP can supply three SBER RAS/regulatory fields.
Historical `known_at` is not proved. Form 101 assets/loans/deposits are not.
See section 9.)

## 3. Source-by-source findings

### 3.1 FNS GIR BO industrial RAS — `NOT_AVAILABLE` for banks

- Endpoint: `bo.nalog.gov.ru` advanced-search + `/nbo/.../bfo/` JSON.
- Industrials: usable RAS lines with `actualBfoDate` / `datePresent` (existing Fundamentals V1).
- Banks: SBER not indexed; hard-deny remains.
- **Must not** map industrial `REVENUE` / `EBITDA` / `TOTAL_DEBT` / operating-income semantics onto banks.

### 3.2 Bank of Russia credit-organisation forms — `PARTIAL`

Probed for SBER (`ogrn=1027700132195`, `regnum=1481`):

| Form | Coverage observed | Surface |
|---|---|---|
| f101 (balance / CoA) | 2007-02 → 2026-09 (221 dates) | HTML tables |
| f102 (P&L) | 2007-04 → 2026-09 (87 dates) | HTML tables |
| f123 (capital) | 2014-02 → 2026-09 (137 dates) | HTML tables |
| f135 | 2010-10 → 2021-04 (127 dates) | HTML tables |

Index URL pattern:

`https://www.cbr.ru/finorg/foinfo/reports/?ogrn={ogrn}`

Form URL pattern:

`https://www.cbr.ru/banking_sector/credit/coinfo/{f101|f102|f123|f135}?regnum={regnum}&dt={YYYY-MM-DD}`

**Why not READY**

- HTML only — no stable public JSON API found.
- No Excel/CSV export discovered on form pages.
- No universe-wide free SECID→regnum registry implemented (only curated SBER mapping).
- `known_at` policy for form publication vs report `dt` not established.
- Fragile HTML cell scraping is **not** accepted as universe-wide READY in this campaign.

**Accepted in V1:** catalog/coverage parser only (`intelligence/banks/cbr_catalog.py`).  
**Not accepted:** inventing NET_PROFIT / NIM / NPL from HTML cells.

### 3.3 ratings.cbr.ru — `REJECTED` (automation)

- Public HTML 200.
- Machine JSON historically behind CSRF + captcha (see `docs/research/public-data-source-audit-v1.md`).
- **No captcha bypass.** Ratings remain UNKNOWN for banks.

### 3.4 MOEX ISS — `PARTIAL` (identity only)

- `iss.moex.com/iss/securities/SBER.json` returns identity / issuesize / ISIN.
- Useful for issuer mapping; **not** bank fundamentals (no NII, NIM, NPL, capital adequacy).

### 3.5 Issuer IR IFRS/RAS — `RESEARCH_ONLY`

- Banks publish IFRS packs on IR sites (PDF/XLS, issuer-specific).
- Probe note: `sberbank.com` IR URLs failed SSL verify in this audit environment (`CERTIFICATE_VERIFY_FAILED` via corporate/self-signed chain).
- Even when reachable: not a stable universe-wide machine feed.
- One-off PDF scraping must not be presented as READY.

### 3.6 Structured free IFRS feed — `NOT_AVAILABLE`

- No free structured IFRS API comparable to FNS industrial RAS JSON was found for Russian banks.

## 4. Candidate bank metrics (availability)

| Metric | Status in V1 |
|---|---|
| NET_INTEREST_INCOME | NOT_AVAILABLE |
| NET_FEE_INCOME | NOT_AVAILABLE |
| NET_PROFIT | PARTIAL — form 0409102 symbol 61101, thousand RUB, not IFRS |
| EQUITY | PARTIAL — form 0409123 line 000 own funds, thousand RUB, not IFRS equity |
| TOTAL_ASSETS | NOT_AVAILABLE — form 101 SOAP data methods empty; HTML totals are not unique |
| LOAN_BOOK | NOT_AVAILABLE |
| DEPOSITS | NOT_AVAILABLE |
| NIM | NOT_AVAILABLE |
| ROE | NOT_AVAILABLE |
| COST_INCOME | NOT_AVAILABLE |
| CAPITAL_ADEQUACY | PARTIAL — form 0409135 ratio Н1.0, percent |
| NPL_RATIO | NOT_AVAILABLE |

NET_PROFIT, EQUITY, and CAPITAL_ADEQUACY can be filled from CreditOrgInfo SOAP
with the definitions in section 9. The other codes stay vocabulary only.

## 5. SBER contract (minimum honesty)

`build_bank_fi_fundamental_snapshot(secid="SBER")` returns:

- `issuer_kind = BANK_FI`
- `status = PARTIAL` (CBR/MOEX surfaces exist) or `NOT_AVAILABLE` if layer collapses
- `metrics = {}` unless SOAP fixtures/live fetch or an explicit bank-capable payload is supplied
- default call does not hit the network and does not embed probed numbers
- industrial ratio codes rejected even if injected
- limitations include `bank_fi_industrial_fns_unsupported` and `INDUSTRIAL_FNS_FALLBACK_FORBIDDEN`
- optional `cbr_form_catalog` fact = coverage metadata, **not** metric values

SBER never receives industrial FNS interpretation.

## 6. Implementation map

| Path | Role |
|---|---|
| `backend/app/modules/intelligence/banks/` | Agent C package |
| `docs/intelligence/bank_sources_audit.md` | this audit |
| `.tmp/agents/c_banks_smoke.json` | local smoke artifact |

## 7. Follow-ups (out of scope)

1. Curated SECID→CBR regnum map for VTBR/BSPB/CBOM after live probes.
2. Bounded form-101/102 parser with explicit account→metric mapping + `known_at` policy (candidate track).
3. Optional IR IFRS structured extract via Agent E (LLM assist, not numerical truth).
4. Do **not** buy paid bank fundamentals vendors for this stack unless OWNER revisits REJECTED_PAID.

## 8. Probe evidence (local, 2026-10-07)

| URL | Result |
|---|---|
| FNS search `7707083893` | 200 JSON, `totalElements=0` |
| CBR SBER reports index | 200 HTML, f101/f102/f123/f135 links |
| CBR f101 `regnum=1481&dt=2026-09-01` | 200 HTML tables, no JSON/export |
| MOEX SBER securities | 200 JSON identity |
| ratings.cbr.ru | 200 HTML (automation rejected) |
| sberbank.com IR | SSL verify failed in audit env |

## 9. Agent D re-audit (2026-10-12) — SBER SOAP

Official free surface: [WSCO](https://www.cbr.ru/development/WSCO/) /
`CreditOrgInfo.asmx`. No CAPTCHA. No paid feed.

Identity: `RegNumToIntCode(1481) = 1315037838265`. `CreditInfoByIntCodeEx`
returns regnum 1481, OGRN `1027700132195`, name ПАО Сбербанк. The payload has
no INN field. Curated INN `7707083893` was not re-proved by this method.

Form calls must pass **regnum 1481**. The internal code overflows SOAP `xsd:int`
(HTTP 500). `Data101FullExV2XML` with that internal code returns `NotFound`.

| Field | Method | Proved value at 2026-09-01 | Definition |
|---|---|---|---|
| EQUITY | `Data123FormFullXML` line `000` | 8092364887 thousand RUB | «Собственные средства (капитал), итого». HTML caption `тыс. рублей`. Same digits on the HTML form. Not IFRS equity. |
| CAPITAL_ADEQUACY | `Data135FormFullXML` `Н1.0` | 13.095 percent | Section 3 actual value. HTML column «Фактическое значение, процент» shows 13,095. |
| NET_PROFIT | `Data102FormXML` symbol `61101` | 1332707281 thousand RUB | Latest indicator symset name: profit after tax. HTML row 61101 shows the same digits. Not IFRS. The series is not summed. |

`known_at` policy: **CURRENT_ONLY**. SOAP exposes `OnDate` / `DT` only.
`period_end` is that report date and is not `known_at`. No historical
publication timestamp is manufactured.

Blockers left in force:

- `Data101FullXML` for regnum 1481 and indicator 20202 returns an empty `FD`
  table. Assets, loan book, and deposits are not emitted.
- HTML form 101 contains several «Итого по активу (баланс)» rows (different
  chapters). That is not a unique total-assets field.
- Status stays **PARTIAL**, not READY: three fields, SBER regnum only, no IFRS,
  no historical PIT.
