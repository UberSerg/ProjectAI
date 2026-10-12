"""Deterministic source-document extractor. No LLM, no network, no shell.

Document text is untrusted data. It is scanned with bounded regex rules only.
It is never passed to a shell, eval, or an HTTP client. Prompt-injection
instructions and fetch/shell lines are dropped and are not facts.

Direction is lexical polarity inside the evidence window. It is not a trading
action and not a predicted return. An increase word does not mean buy.
Materiality is the importance of the event class, not an expected price move.
Confidence is rule strength in [0, 1], not a probability of profit.

Idempotency key (persisted on the claim and on the event payload):

    {source_document_id}|{extractor_version}|{event_type}|{claim_hash}

claim_hash is sha256 of event_type, rule_id, and the normalized evidence
fragment. A new document revision is a new source_documents row and therefore
a new source_document_id; this module never updates or deletes prior facts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.modules.intelligence.extraction.sanitize import document_contains_injection

DETERMINISTIC_EXTRACTOR_VERSION = "deterministic_extractor_v1"

MAX_SCAN_CHARS = 20_000
EVIDENCE_MAX_CHARS = 400

# Importance of the event class. Not a forecast of return.
MATERIALITY_WEIGHT: dict[str, float | None] = {
    "HIGH": 1.0,
    "MEDIUM": 0.6,
    "LOW": 0.3,
    "UNKNOWN": None,
}

# Explicit improvement or relief language. Not a recommendation to buy.
_POSITIVE_WORDS: tuple[str, ...] = (
    "increased",
    "increase",
    "increases",
    "raised",
    "raises",
    "higher",
    "grew",
    "grown",
    "growth",
    "rose",
    "risen",
    "beat",
    "beaten",
    "exceeded",
    "upgrade",
    "upgraded",
    "improved",
    "improvement",
)
_POSITIVE_STEMS: tuple[str, ...] = (
    "увеличил",
    "увеличива",
    "повысил",
    "вырос",
    "превысил",
)

# Explicit deterioration or adverse-action language. Not a recommendation to sell.
# "sanction" / "fine" / "penalty" are adverse because the rule table says so,
# except when a relief phrase above them already matched.
_NEGATIVE_WORDS: tuple[str, ...] = (
    "decreased",
    "decrease",
    "decreases",
    "cut",
    "cuts",
    "reduced",
    "reduce",
    "lowered",
    "fell",
    "fallen",
    "missed",
    "downgrade",
    "downgraded",
    "loss",
    "losses",
    "suspended",
    "cancelled",
    "canceled",
    "default",
    "defaulted",
    "sanction",
    "sanctions",
    "sanctioned",
    "fine",
    "fined",
    "penalty",
    "penalties",
    "banned",
    "halt",
    "halted",
    "accident",
    "explosion",
    "outage",
    "fired",
    "dismissed",
)
_NEGATIVE_STEMS: tuple[str, ...] = (
    "снизил",
    "сократил",
    "упал",
    "убыт",
    "отменил",
    "санкц",
    "штраф",
    "авар",
)

# Explicit "no change" language. Absence of a pole is UNKNOWN, never NEUTRAL.
_NEUTRAL_PHRASES: tuple[str, ...] = (
    "unchanged",
    "maintained",
    "in line",
    "held flat",
    "remained flat",
    "без изменений",
    "на прежнем уровне",
)

# Checked before the generic sanction/fine tokens so relief is not NEGATIVE.
_RELIEF_PHRASES: tuple[str, ...] = (
    "sanctions lifted",
    "sanction lifted",
    "sanctions removed",
    "sanction relief",
    "lifted sanctions",
    "removed sanctions",
    "санкции сняты",
    "санкции отменены",
)

_NEGATION_PREFIX = re.compile(r"(?:^|[\s])(?:not|no|never|не|нет)\s*$", re.I)

# Shell / fetch instructions. These are not facts and are never executed.
_SHELL_OR_FETCH = re.compile(
    r"(invoke-(?:webrequest|expression|command|restmethod)\b"
    r"|\bpowershell(?:\.exe)?\b"
    r"|\bcmd(?:\.exe)?\s*/c\b"
    r"|\b(?:curl|wget)\b"
    r"|\bfetch\s+https?://)",
    re.I,
)

_AMOUNT = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*"
    r"(?P<scale>billion|million|bln|mln|млрд|млн)\s*"
    r"(?P<currency>RUB|USD|EUR|GBP|руб(?:\.|лей|ля)?|долл(?:\.|аров)?)?",
    re.I,
)
_AMOUNT_CCY = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*"
    r"(?P<currency>RUB|USD|EUR|GBP|руб(?:\.|лей|ля)?|долл(?:\.|аров)?)"
    r"(?:\s*per\s+share|\s*на\s+акцию)?",
    re.I,
)
_PERCENT = re.compile(r"(?P<pct>\d+(?:[.,]\d+)?)\s*%")
_RANGE = re.compile(
    r"from\s+(?P<low>\d+(?:[.,]\d+)?)\s*"
    r"(?P<low_unit>billion|million|bln|mln|%|RUB|USD|EUR)?\s*"
    r"to\s+(?P<high>\d+(?:[.,]\d+)?)\s*"
    r"(?P<high_unit>billion|million|bln|mln|%|RUB|USD|EUR|млрд|млн)?",
    re.I,
)
_ISO_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_QUOTED_NAME = re.compile(r"[«\"]([^»\"]{2,80})[»\"]")
_PER_SHARE = re.compile(r"per\s+share|на\s+акцию", re.I)
_EXPLICIT_PERIOD = re.compile(
    r"(?:\b(?:for|in|FY)\s+|\bза\s+)(?:(Q[1-4])\s*)?(20\d{2})\b",
    re.I,
)
_QUARTER_PERIOD = re.compile(r"\b(Q[1-4])\s*(20\d{2})\b", re.I)
_ACTIONS = (
    "approved",
    "declared",
    "recommended",
    "increased",
    "cut",
    "suspended",
    "cancelled",
    "canceled",
    "reported",
    "sanctioned",
    "imposed",
    "appointed",
    "resigned",
    "acquired",
    "announced",
    "issued",
    "fined",
    "утвердил",
    "объявил",
    "рекомендовал",
    "отменил",
)

_SCALE_NORM = {
    "billion": "billion",
    "bln": "billion",
    "млрд": "billion",
    "million": "million",
    "mln": "million",
    "млн": "million",
}


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: str
    event_type: str
    # Class importance. Not predicted return.
    materiality: str
    affected_horizon: str
    pattern: re.Pattern[str]


# First matching rule wins inside one sentence. Patterns are type detectors only;
# polarity is a separate table so "increased" does not itself choose the type.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        "sanction.regulatory",
        "SANCTION_REGULATORY",
        "HIGH",
        "immediate",
        re.compile(r"\b(?:sanctions?|sanctioned|penalt(?:y|ies)|fined)\b|санкц|штраф", re.I),
    ),
    _Rule(
        "operational.incident",
        "OPERATIONAL_INCIDENT",
        "HIGH",
        "immediate",
        re.compile(
            r"\b(?:accident|explosion|outage|halted\s+production|production\s+halt)\b|авар|пожар",
            re.I,
        ),
    ),
    _Rule(
        "legal.matter",
        "LEGAL",
        "MEDIUM",
        "unspecified",
        re.compile(r"\b(?:lawsuit|litigation|filed\s+suit|sued)\b|судебн\w+\s+иск|подал\w*\s+иск", re.I),
    ),
    _Rule(
        "m_and_a.transaction",
        "M_AND_A",
        "HIGH",
        "unspecified",
        re.compile(
            r"\b(?:acquisition\s+of|merger\s+with|agreed\s+to\s+acquire|takeover\s+of)\b|поглощен|слияни",
            re.I,
        ),
    ),
    _Rule(
        "spo.secondary",
        "SPO_SECONDARY",
        "MEDIUM",
        "unspecified",
        re.compile(
            r"\bSPO\b|secondary\s+offering|follow-on\s+offering|допэмисс|дополнительн\w+\s+эмисс",
            re.I,
        ),
    ),
    _Rule(
        "buyback.program",
        "BUYBACK",
        "MEDIUM",
        "unspecified",
        re.compile(r"\b(?:buyback|share\s+repurchase|repurchase\s+program)\b|обратн\w+\s+выкуп", re.I),
    ),
    _Rule(
        "debt.financing",
        "DEBT_FINANCING",
        "MEDIUM",
        "unspecified",
        re.compile(
            r"\b(?:bond\s+issue|issued\s+bonds|debt\s+issuance|credit\s+facility)\b"
            r"|разместил\w*\s+облигац|выпуск\s+облигац",
            re.I,
        ),
    ),
    _Rule(
        "guidance.statement",
        "GUIDANCE",
        "MEDIUM",
        "forward",
        re.compile(r"\b(?:guidance|outlook)\b|прогноз", re.I),
    ),
    _Rule(
        "earnings.results",
        "EARNINGS_RESULTS",
        "HIGH",
        "reporting_period",
        re.compile(
            r"\b(?:earnings|net\s+income|net\s+profit|revenue|ebitda)\b|чистая\s+прибыл|выручк",
            re.I,
        ),
    ),
    _Rule(
        "dividend.mention",
        "DIVIDEND",
        "MEDIUM",
        "capital_return",
        re.compile(r"\bdividends?\b|дивиденд", re.I),
    ),
    _Rule(
        "capex.plan",
        "CAPEX",
        "MEDIUM",
        "forward",
        re.compile(r"\bcapex\b|capital\s+expenditure|капитальн\w+\s+(?:затрат|вложен)", re.I),
    ),
    _Rule(
        "management.change",
        "MANAGEMENT",
        "LOW",
        "unspecified",
        re.compile(
            r"\b(?:appointed|named|resigned|stepped\s+down)\b.{0,48}\b(?:CEO|CFO|chairman|chair)\b"
            r"|\b(?:CEO|CFO|chairman)\b.{0,48}\b(?:appointed|resigned|stepped\s+down|replaced)\b"
            r"|гендиректор.{0,48}(?:назначен|отставк)",
            re.I,
        ),
    ),
    _Rule(
        "corporate.action",
        "CORPORATE_ACTION",
        "MEDIUM",
        "unspecified",
        re.compile(
            r"\b(?:stock\s+split|share\s+split|spin-off|spinoff|delisting)\b|дроблени\w+\s+акци|делистинг",
            re.I,
        ),
    ),
    _Rule(
        "other.material",
        "OTHER_MATERIAL",
        "UNKNOWN",
        "unspecified",
        re.compile(r"\bmaterial\s+event\b|существенн\w+\s+событи", re.I),
    ),
)


@dataclass(frozen=True, slots=True)
class DeterministicFact:
    event_type: str
    materiality: str
    direction: str
    affected_horizon: str
    evidence_fragment: str
    confidence: float
    rule_id: str
    claim_hash: str
    fields: dict[str, object]
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class DeterministicScan:
    facts: tuple[DeterministicFact, ...]
    injection_sentences_rejected: int
    document_has_injection: bool
    truncated: bool


def build_idempotency_key(source_document_id: int, event_type: str, claim_hash: str) -> str:
    """Stable key for one document revision + extractor + type + evidence."""
    return f"{source_document_id}|{DETERMINISTIC_EXTRACTOR_VERSION}|{event_type}|{claim_hash}"


def claim_hash_for(event_type: str, rule_id: str, evidence_fragment: str) -> str:
    normalized = " ".join(evidence_fragment.casefold().split())
    blob = f"{event_type}\n{rule_id}\n{normalized}".encode()
    return hashlib.sha256(blob).hexdigest()


def direction_from_evidence(evidence: str) -> str:
    """Lexical polarity inside the evidence window.

    POSITIVE / NEGATIVE / NEUTRAL require an explicit token from the tables in
    this module. If the window does not justify a pole, return UNKNOWN.
    Both poles together also return UNKNOWN (MIXED stays a contract label only).
    Never coerce UNKNOWN to NEUTRAL.
    """
    folded = evidence.casefold()
    if any(phrase in folded for phrase in _RELIEF_PHRASES):
        return "POSITIVE"
    positive = _any_token(folded, _POSITIVE_WORDS, _POSITIVE_STEMS)
    negative = _any_token(folded, _NEGATIVE_WORDS, _NEGATIVE_STEMS)
    if positive and negative:
        return "UNKNOWN"
    if negative:
        return "NEGATIVE"
    if positive:
        return "POSITIVE"
    if any(phrase in folded for phrase in _NEUTRAL_PHRASES):
        return "NEUTRAL"
    return "UNKNOWN"


def rule_strength(*, has_amount: bool, direction: str) -> float:
    """Rule strength in [0, 1]. Not a probability of profit."""
    has_polarity = direction != "UNKNOWN"
    if has_amount and has_polarity:
        return 0.85
    if has_amount:
        return 0.75
    if has_polarity:
        return 0.65
    return 0.55


def scan_document_text(raw_text: str | None) -> DeterministicScan:
    """Scan at most the first MAX_SCAN_CHARS. Injection lines are not facts."""
    if not raw_text:
        return DeterministicScan((), 0, False, False)
    truncated = len(raw_text) > MAX_SCAN_CHARS
    bounded = raw_text[:MAX_SCAN_CHARS]
    facts: list[DeterministicFact] = []
    seen_hashes: set[str] = set()
    rejected = 0
    document_injection = _is_instruction(bounded)
    cursor = 0
    for sentence in _sentences(bounded):
        start = bounded.find(sentence, cursor)
        if start < 0:
            start = cursor
        end = start + len(sentence)
        cursor = end
        if _is_instruction(sentence):
            rejected += 1
            continue
        fact = _fact_from_sentence(sentence, char_start=start, char_end=end)
        if fact is None or fact.claim_hash in seen_hashes:
            continue
        seen_hashes.add(fact.claim_hash)
        facts.append(fact)
    return DeterministicScan(
        facts=tuple(facts),
        injection_sentences_rejected=rejected,
        document_has_injection=document_injection,
        truncated=truncated,
    )


def _is_instruction(text: str) -> bool:
    if document_contains_injection(text):
        return True
    return _SHELL_OR_FETCH.search(text) is not None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def _fact_from_sentence(sentence: str, *, char_start: int, char_end: int) -> DeterministicFact | None:
    rule: _Rule | None = None
    match: re.Match[str] | None = None
    for candidate in _RULES:
        found = candidate.pattern.search(sentence)
        if found:
            rule = candidate
            match = found
            break
    if rule is None or match is None:
        return None
    evidence = _evidence_window(sentence, match)
    fields = _drop_fields_missing_from_evidence(
        _fields_from_sentence(sentence, event_type=rule.event_type),
        evidence,
    )
    direction = direction_from_evidence(evidence)
    has_amount = "amount" in fields or "percentage" in fields or "guidance_low" in fields
    confidence = rule_strength(has_amount=has_amount, direction=direction)
    digest = claim_hash_for(rule.event_type, rule.rule_id, evidence)
    return DeterministicFact(
        event_type=rule.event_type,
        materiality=rule.materiality,
        direction=direction,
        affected_horizon=rule.affected_horizon,
        evidence_fragment=evidence,
        confidence=confidence,
        rule_id=rule.rule_id,
        claim_hash=digest,
        fields=fields,
        char_start=char_start,
        char_end=char_end,
    )


def _evidence_window(sentence: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 160)
    end = min(len(sentence), match.end() + 160)
    fragment = " ".join(sentence[start:end].split())
    if len(fragment) > EVIDENCE_MAX_CHARS:
        fragment = fragment[:EVIDENCE_MAX_CHARS]
    return fragment


def _fields_from_sentence(sentence: str, *, event_type: str) -> dict[str, object]:
    """Copy only numbers and names that appear in this sentence. Omit the rest."""
    fields: dict[str, object] = {}
    range_span: tuple[int, int] | None = None
    range_match = _RANGE.search(sentence)
    if range_match and event_type == "GUIDANCE":
        fields["guidance_low"] = _parse_number(range_match.group("low"))
        fields["guidance_high"] = _parse_number(range_match.group("high"))
        unit = range_match.group("high_unit") or range_match.group("low_unit")
        if unit:
            norm_scale = _SCALE_NORM.get(unit.casefold())
            if norm_scale:
                fields["scale"] = norm_scale
            elif unit == "%":
                fields["guidance_unit"] = "percent"
            else:
                fields["currency"] = _normalize_currency(unit)
        range_span = range_match.span()

    percent = _PERCENT.search(sentence)
    if percent and not _overlaps(percent.span(), range_span):
        fields["percentage"] = _parse_number(percent.group("pct"))

    amount = _first_amount(sentence, skip=range_span)
    if amount is not None:
        value, scale, currency = amount
        if "percentage" not in fields or currency or scale:
            fields["amount"] = value
        if scale:
            fields["scale"] = scale
        if currency and "currency" not in fields:
            fields["currency"] = currency

    if _PER_SHARE.search(sentence):
        fields["unit"] = "per_share"

    period = _period_from(sentence)
    if period:
        fields["period"] = period

    iso = _ISO_DATE.search(sentence)
    if iso:
        fields["event_date"] = iso.group(1)

    company = _QUOTED_NAME.search(sentence)
    if company and "http" not in company.group(1).casefold():
        fields["company"] = company.group(1).strip()

    if event_type == "M_AND_A":
        counterparty = re.search(
            r"(?:acquisition\s+of|merger\s+with|agreed\s+to\s+acquire|takeover\s+of)\s+"
            r"([A-Z][A-Za-z0-9&.'\- ]{1,60})",
            sentence,
        )
        if counterparty:
            fields["counterparty"] = " ".join(counterparty.group(1).split())

    action = _action_from(sentence)
    if action:
        fields["action"] = action
    return fields


def _first_amount(
    sentence: str, *, skip: tuple[int, int] | None
) -> tuple[float, str | None, str | None] | None:
    for pattern in (_AMOUNT, _AMOUNT_CCY):
        for match in pattern.finditer(sentence):
            if _overlaps(match.span(), skip):
                continue
            if _overlaps(match.span(), _percent_span(sentence)):
                continue
            scale_raw = match.groupdict().get("scale")
            currency_raw = match.groupdict().get("currency")
            if not scale_raw and not currency_raw:
                continue
            scale = _SCALE_NORM.get(scale_raw.casefold()) if scale_raw else None
            currency = _normalize_currency(currency_raw) if currency_raw else None
            return _parse_number(match.group("value")), scale, currency
    return None


def _percent_span(sentence: str) -> tuple[int, int] | None:
    match = _PERCENT.search(sentence)
    return match.span() if match else None


def _overlaps(span: tuple[int, int], other: tuple[int, int] | None) -> bool:
    if other is None:
        return False
    return span[0] < other[1] and other[0] < span[1]


def _period_from(sentence: str) -> str | None:
    """Year is a period only with for/in/за/FY/Q, so a bare calendar year is not an amount."""
    explicit = _EXPLICIT_PERIOD.search(sentence)
    if explicit:
        quarter = explicit.group(1)
        year = explicit.group(2)
        return f"{quarter.upper()} {year}" if quarter else year
    quarter = _QUARTER_PERIOD.search(sentence)
    if quarter:
        return f"{quarter.group(1).upper()} {quarter.group(2)}"
    return None


def _drop_fields_missing_from_evidence(fields: dict[str, object], evidence: str) -> dict[str, object]:
    """Drop captured values whose text is outside the stored evidence fragment."""
    kept = dict(fields)
    folded = " ".join(evidence.casefold().split())
    for key in ("amount", "percentage", "guidance_low", "guidance_high"):
        value = kept.get(key)
        if isinstance(value, int | float) and not _number_visible(float(value), folded):
            kept.pop(key, None)
    if "amount" not in kept and "guidance_low" not in kept:
        kept.pop("scale", None)
        if "percentage" not in kept:
            kept.pop("currency", None)
    period = kept.get("period")
    if isinstance(period, str) and period.casefold() not in folded:
        kept.pop("period", None)
    if kept.get("unit") == "per_share" and _PER_SHARE.search(evidence) is None:
        kept.pop("unit", None)
    for key in ("event_date", "company", "counterparty", "action"):
        value = kept.get(key)
        if isinstance(value, str) and value.casefold() not in folded:
            kept.pop(key, None)
    return kept


def _number_visible(value: float, evidence: str) -> bool:
    token = str(int(value)) if float(value).is_integer() else str(value)
    if token in evidence:
        return True
    return token.replace(".", ",") in evidence


def _action_from(sentence: str) -> str | None:
    folded = sentence.casefold()
    for action in _ACTIONS:
        if re.search(rf"(?<!\w){re.escape(action)}(?!\w)", folded):
            return action
    return None


def _parse_number(raw: str) -> float:
    cleaned = raw.strip().replace(" ", "").replace("\u00a0", "")
    if "," in cleaned and "." not in cleaned:
        left, right = cleaned.split(",", 1)
        if len(right) == 3 and left.isdigit() and right.isdigit():
            cleaned = left + right
        else:
            cleaned = left + "." + right
    return float(cleaned)


def _normalize_currency(raw: str) -> str:
    token = raw.casefold().rstrip(".")
    if token.startswith("руб"):
        return "RUB"
    if token.startswith("долл"):
        return "USD"
    return raw.upper()


def _any_token(folded: str, words: tuple[str, ...], stems: tuple[str, ...]) -> bool:
    for word in words:
        if _word_present(folded, word):
            return True
    for stem in stems:
        if _stem_present(folded, stem):
            return True
    return False


def _word_present(folded: str, word: str) -> bool:
    pattern = re.compile(rf"(?<!\w){re.escape(word)}(?!\w)")
    for match in pattern.finditer(folded):
        if not _negated(folded, match.start()):
            return True
    return False


def _stem_present(folded: str, stem: str) -> bool:
    pattern = re.compile(rf"(?<!\w){re.escape(stem)}")
    for match in pattern.finditer(folded):
        if not _negated(folded, match.start()):
            return True
    return False


def _negated(folded: str, start: int) -> bool:
    prefix = folded[max(0, start - 16) : start]
    return _NEGATION_PREFIX.search(prefix) is not None
