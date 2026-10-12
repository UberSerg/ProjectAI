"""Company resolution without a live MOEX or database.

Instrument and issuer ids in this file are fixture values, not master keys.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.modules.fundamentals.application.pit import IssuerResolution
from app.modules.fundamentals.domain.types import MappingStatus
from app.modules.intelligence.news.models import IntelligenceSourceDocument
from app.modules.intelligence.resolution.decide import (
    BASIS_INN,
    BASIS_ISIN,
    BASIS_NAME,
    BASIS_OGRN,
    BASIS_SECID,
    BASIS_UNMAPPED,
    CONFIDENCE_CONFLICT,
    CONFIDENCE_EXACT,
    CONFIDENCE_HIGH,
    CONFIDENCE_NONE,
    MasterIdentityRow,
    ResolutionCandidate,
    assemble_candidates,
    resolve_company,
)
from app.modules.intelligence.resolution.session import (
    load_resolution_candidates,
    resolve_source_document,
)

_SEMANTIC = frozenset({CONFIDENCE_EXACT, CONFIDENCE_HIGH, CONFIDENCE_CONFLICT, CONFIDENCE_NONE})


def _candidate(**overrides: object) -> ResolutionCandidate:
    data: dict[str, object] = {
        "instrument_id": 501,
        "issuer_id": 601,
        "symbol": "SBER",
        "isins": ("RU0009029540",),
        "inns": ("7707083893",),
        "ogrns": ("1027700132195",),
        "names": ("ПАО Сбербанк",),
    }
    data.update(overrides)
    return ResolutionCandidate(**data)  # type: ignore[arg-type]


def _sber() -> ResolutionCandidate:
    return _candidate()


def _lkoh() -> ResolutionCandidate:
    return _candidate(
        instrument_id=502,
        issuer_id=602,
        symbol="LKOH",
        isins=("RU0009024277",),
        inns=("7708004767",),
        ogrns=("1027700035769",),
        names=("ПАО ЛУКОЙЛ",),
    )


def _mgnt() -> ResolutionCandidate:
    return _candidate(
        instrument_id=503,
        issuer_id=603,
        symbol="MGNT",
        isins=("RU000A0JKQU8",),
        inns=("2309085638",),
        ogrns=("1032304945947",),
        names=("ПАО Магнит", "Магнит"),
    )


def _assert_semantic(confidence: str) -> None:
    assert isinstance(confidence, str)
    assert confidence in _SEMANTIC
    assert not confidence.replace(".", "", 1).isdigit()


def test_exact_secid_maps_sber() -> None:
    decision = resolve_company("Совет директоров SBER рекомендовал дивиденды.", [_sber(), _lkoh(), _mgnt()])
    assert decision.status == MappingStatus.MAPPED.value
    assert decision.mapping_basis == BASIS_SECID
    assert decision.confidence_semantic == CONFIDENCE_EXACT
    assert decision.instrument_id == 501
    assert decision.issuer_id == 601
    assert decision.matched_identifiers[0].as_dict() == {"kind": "SECID", "value": "SBER"}
    assert decision.candidate_conflicts == ()
    _assert_semantic(decision.confidence_semantic)


def test_secid_outranks_another_official_name() -> None:
    decision = resolve_company("В заметке о ЛУКОЙЛ упомянут тикер SBER.", [_sber(), _lkoh()])
    assert decision.status == MappingStatus.MAPPED.value
    assert decision.mapping_basis == BASIS_SECID
    assert decision.instrument_id == 501


def test_two_tickers_stay_ambiguous() -> None:
    decision = resolve_company("Идеи дня: SBER и LKOH.", [_sber(), _lkoh(), _mgnt()])
    assert decision.status == MappingStatus.AMBIGUOUS.value
    assert decision.mapping_basis == BASIS_SECID
    assert decision.confidence_semantic == CONFIDENCE_CONFLICT
    assert decision.instrument_id is None
    assert decision.issuer_id is None
    assert {item.symbol for item in decision.candidate_conflicts} == {"SBER", "LKOH"}


def test_exact_isin_maps_lkoh() -> None:
    text = "Идентификатор выпуска RU0009024277 указан в сообщении."
    decision = resolve_company(text, [_sber(), _lkoh(), _mgnt()])
    assert decision.status == MappingStatus.MAPPED.value
    assert decision.mapping_basis == BASIS_ISIN
    assert decision.instrument_id == 502
    assert decision.issuer_id == 602
    assert decision.matched_identifiers[0].as_dict() == {"kind": "ISIN", "value": "RU0009024277"}


def test_exact_inn_maps_mgnt() -> None:
    decision = resolve_company("ИНН 2309085638 раскрыт в карточке эмитента.", [_sber(), _lkoh(), _mgnt()])
    assert decision.status == MappingStatus.MAPPED.value
    assert decision.mapping_basis == BASIS_INN
    assert decision.instrument_id == 503
    assert decision.issuer_id == 603
    assert decision.matched_identifiers[0].value == "2309085638"


def test_exact_ogrn_maps_when_present_on_issuer() -> None:
    decision = resolve_company(
        "ОГРН 1027700132195 подтверждён в карточке.",
        [_sber(), _lkoh(), _mgnt()],
    )
    assert decision.status == MappingStatus.MAPPED.value
    assert decision.mapping_basis == BASIS_OGRN
    assert decision.instrument_id == 501
    assert decision.issuer_id == 601


def test_unique_official_name_maps() -> None:
    decision = resolve_company(
        "Совет директоров ПАО «Сбербанк» утвердил повестку.",
        [_sber(), _lkoh(), _mgnt()],
    )
    assert decision.status == MappingStatus.MAPPED.value
    assert decision.mapping_basis == BASIS_NAME
    assert decision.confidence_semantic == CONFIDENCE_HIGH
    assert decision.instrument_id == 501
    _assert_semantic(decision.confidence_semantic)


def test_ambiguous_name_does_not_pick_first_company() -> None:
    decision = resolve_company("Сбербанк и ЛУКОЙЛ направили комментарии.", [_sber(), _lkoh(), _mgnt()])
    assert decision.status == MappingStatus.AMBIGUOUS.value
    assert decision.mapping_basis == BASIS_NAME
    assert decision.instrument_id is None
    assert decision.issuer_id is None
    assert [item.symbol for item in decision.candidate_conflicts] == ["LKOH", "SBER"]


def test_ticker_substring_is_rejected() -> None:
    text = "Котировка SBERBANK и преф SBERP не равны XSBER."
    decision = resolve_company(text, [_sber(), _lkoh()])
    assert decision.status == MappingStatus.UNMAPPED.value
    assert decision.mapping_basis == BASIS_UNMAPPED
    assert decision.instrument_id is None
    assert decision.issuer_id is None
    assert decision.candidate_conflicts == ()


def test_generic_banking_sector_article_is_not_sber() -> None:
    text = (
        "Банк России принял решение по ключевой ставке. "
        "Банковский сектор сохраняет запас капитала. "
        "Кредитные организации продолжают кредитование экономики. "
        "Норматив достаточности капитала сберегательных организаций "
        "не привязан к отдельному эмитенту."
    )
    decision = resolve_company(text, [_sber(), _lkoh(), _mgnt()])
    assert decision.status == MappingStatus.UNMAPPED.value
    assert decision.mapping_basis == BASIS_UNMAPPED
    assert decision.confidence_semantic == CONFIDENCE_NONE
    assert decision.instrument_id is None
    assert decision.issuer_id is None
    assert decision.matched_identifiers == ()


def test_extra_bank_symbol_maps_only_as_a_candidate() -> None:
    text = "Комментарий VTBR для инвесторов."
    absent = resolve_company(text, [_sber(), _lkoh(), _mgnt()])
    assert absent.status == MappingStatus.UNMAPPED.value
    assert absent.instrument_id is None

    vtbr = _candidate(
        instrument_id=504,
        issuer_id=604,
        symbol="VTBR",
        isins=(),
        inns=(),
        ogrns=(),
        names=("Банк ВТБ",),
    )
    present = resolve_company(text, [_sber(), vtbr])
    assert present.status == MappingStatus.MAPPED.value
    assert present.mapping_basis == BASIS_SECID
    assert present.instrument_id == 504
    assert present.issuer_id == 604
    assert present.matched_identifiers[0].value == "VTBR"


def test_known_at_is_unchanged(monkeypatch) -> None:
    known = datetime(2024, 3, 15, 18, 45, tzinfo=UTC)
    observed = datetime(2024, 3, 15, 18, 40, tzinfo=UTC)
    published = datetime(2024, 3, 15, 9, 0, tzinfo=UTC)
    document = IntelligenceSourceDocument(
        document_key="cbr:sber:1",
        provider="cbr",
        source_type="PRESS_RELEASE",
        title="Дивиденды SBER",
        published_at=published,
        observed_at=observed,
        known_at=known,
        content_hash="hash-1",
        raw_text="Совет директоров рекомендовал выплату.",
        metadata_={"known_at_basis": "OBSERVED_AT"},
        revision=1,
        parse_status="RAW",
    )
    seen: dict[str, date] = {}

    def _load(session, as_of: date):  # noqa: ANN001
        seen["as_of"] = as_of
        return [_sber(), _lkoh()]

    monkeypatch.setattr(
        "app.modules.intelligence.resolution.session.load_resolution_candidates",
        _load,
    )
    decision = resolve_source_document(MagicMock(), document)

    assert document.known_at == known
    assert document.observed_at == observed
    assert document.published_at == published
    assert seen["as_of"] == date(2024, 3, 15)
    assert decision.status == MappingStatus.MAPPED.value
    assert document.instrument_id == 501
    assert document.issuer_id == 601
    assert document.mapping_basis == BASIS_SECID
    record = document.metadata_["company_resolution"]
    assert record["resolver_version"] == "company-resolution-v1"
    assert record["status"] == MappingStatus.MAPPED.value
    assert record["confidence_semantic"] == CONFIDENCE_EXACT
    assert record["matched_identifiers"] == [{"kind": "SECID", "value": "SBER"}]
    assert record["candidate_conflicts"] == []
    assert document.metadata_["known_at_basis"] == "OBSERVED_AT"
    _assert_semantic(record["confidence_semantic"])


def test_pit_unmapped_issuer_is_not_a_candidate() -> None:
    row = _master_row(mapping_status=MappingStatus.MAPPED.value)
    assert assemble_candidates([row], {503: (MappingStatus.UNMAPPED.value, None)}) == []


def test_unmapped_master_row_is_ignored_even_if_pit_says_mapped() -> None:
    row = _master_row(mapping_status=MappingStatus.UNMAPPED.value)
    assert assemble_candidates([row], {503: (MappingStatus.MAPPED.value, 603)}) == []


def test_loader_uses_pit_issuer_from_master(monkeypatch) -> None:
    instrument = SimpleNamespace(id=17, symbol="MGNT", name="Магнит", isin="RU000A0JKQU8")
    mapping = SimpleNamespace(
        instrument_id=17,
        issuer_id=27,
        external_secid="MGNT",
        isin="RU000A0JKQU8",
        mapping_status=MappingStatus.MAPPED.value,
    )
    issuer = SimpleNamespace(
        id=27,
        title="ПАО Магнит",
        title_en="Magnit",
        inn="2309085638",
        metadata_={"ogrn": "1032304945947", "fns": {"short_name": "Магнит"}},
    )
    session = MagicMock()
    session.execute.return_value.all.return_value = [(instrument, mapping, issuer)]
    calls: list[tuple[int, date]] = []

    def _pit(bound_session, instrument_id: int, as_of: date):  # noqa: ANN001
        calls.append((instrument_id, as_of))
        return IssuerResolution(27, "CURRENT_ONLY", MappingStatus.MAPPED.value)

    monkeypatch.setattr(
        "app.modules.intelligence.resolution.session.resolve_issuer_for_instrument",
        _pit,
    )
    found = load_resolution_candidates(session, date(2024, 3, 15))
    assert calls == [(17, date(2024, 3, 15))]
    assert len(found) == 1
    assert found[0].symbol == "MGNT"
    assert found[0].instrument_id == 17
    assert found[0].issuer_id == 27
    assert "2309085638" in found[0].inns
    assert "1032304945947" in found[0].ogrns
    assert "Магнит" in found[0].names

    def _unmapped(bound_session, instrument_id: int, as_of: date):  # noqa: ANN001
        return IssuerResolution(None, "UNMAPPED", MappingStatus.UNMAPPED.value)

    monkeypatch.setattr(
        "app.modules.intelligence.resolution.session.resolve_issuer_for_instrument",
        _unmapped,
    )
    assert load_resolution_candidates(session, date(2024, 3, 15)) == []


def _master_row(**overrides: object) -> MasterIdentityRow:
    data: dict[str, object] = {
        "instrument_id": 503,
        "symbol": "MGNT",
        "instrument_name": "Магнит",
        "instrument_isin": "RU000A0JKQU8",
        "issuer_id": 603,
        "title": "ПАО Магнит",
        "title_en": "Magnit",
        "inn": "2309085638",
        "issuer_metadata": {"ogrn": "1032304945947"},
        "external_secid": "MGNT",
        "mapping_isin": "RU000A0JKQU8",
        "mapping_status": MappingStatus.MAPPED.value,
    }
    data.update(overrides)
    return MasterIdentityRow(**data)  # type: ignore[arg-type]
