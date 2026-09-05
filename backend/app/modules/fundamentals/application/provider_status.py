"""Operational status for fundamentals data providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.modules.fundamentals.domain.types import (
    SOURCE_EDISCLOSURE_GATEWAY,
    SOURCE_GIR_BO,
    SOURCE_MOEX_ISS,
    AccessModel,
    ProviderOperationalStatus,
    TimestampQuality,
)
from app.modules.fundamentals.infrastructure.edisclosure_gateway import (
    AuthParams,
    EdisclosureGatewayClient,
    humanize_auth_failure,
    redact_secrets,
)
from app.modules.fundamentals.infrastructure.gir_bo_client import (
    GirBoClient,
    classify_gir_bo_access,
    subscription_required_message,
)


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    provider: str
    configured: bool
    enabled: bool
    reachable: bool | None
    authenticated: bool | None
    operational_status: ProviderOperationalStatus
    pit_capability: str
    timestamp_quality: TimestampQuality
    access_model: AccessModel
    last_successful_request: str | None
    human_explanation: str
    pit_safe: bool


def _moex_status(settings: Settings) -> ProviderProbeResult:
    return ProviderProbeResult(
        provider=SOURCE_MOEX_ISS,
        configured=True,
        enabled=True,
        reachable=True,
        authenticated=True,
        operational_status=ProviderOperationalStatus.READY,
        pit_capability="ISSUER_IDENTITY",
        timestamp_quality=TimestampQuality.NONE,
        access_model=AccessModel.PUBLIC_API,
        last_successful_request=None,
        human_explanation=(
            "MOEX ISS /iss/securities.json — идентичность эмитента по точному SECID, "
            "без отчётности и дивидендов."
        ),
        pit_safe=True,
    )


def probe_edisclosure_gateway(
    *,
    settings: Settings | None = None,
    client: EdisclosureGatewayClient | None = None,
    live: bool = False,
) -> ProviderProbeResult:
    settings = settings or get_settings()
    configured = bool(settings.edisclosure_gateway_enabled)
    has_credentials = bool(
        settings.edisclosure_gateway_username.strip() and settings.edisclosure_gateway_secret
    )
    if not configured:
        return ProviderProbeResult(
            provider=SOURCE_EDISCLOSURE_GATEWAY,
            configured=False,
            enabled=False,
            reachable=None,
            authenticated=None,
            operational_status=ProviderOperationalStatus.READY_REQUIRES_CREDENTIALS,
            pit_capability="DISCLOSURE_EVENTS",
            timestamp_quality=TimestampQuality.EXACT_TIMESTAMP,
            access_model=AccessModel.CREDENTIALS_REQUIRED,
            last_successful_request=None,
            human_explanation=(
                "У провайдера есть отдельный Data Gateway (OpenAPI). Обычный сайт e-disclosure "
                "не предназначен для автоматического доступа. Нужны учётные данные по договору "
                "(EDISCLOSURE_GATEWAY_ENABLED + USERNAME/SECRET). Сейчас адаптер выключен."
            ),
            pit_safe=False,
        )
    if not has_credentials:
        return ProviderProbeResult(
            provider=SOURCE_EDISCLOSURE_GATEWAY,
            configured=True,
            enabled=True,
            reachable=None,
            authenticated=False,
            operational_status=ProviderOperationalStatus.READY_REQUIRES_CREDENTIALS,
            pit_capability="DISCLOSURE_EVENTS",
            timestamp_quality=TimestampQuality.EXACT_TIMESTAMP,
            access_model=AccessModel.CREDENTIALS_REQUIRED,
            last_successful_request=None,
            human_explanation=(
                "Шлюз данных e-disclosure доступен по OpenAPI, но учётные данные не заданы "
                "(EDISCLOSURE_GATEWAY_USERNAME / EDISCLOSURE_GATEWAY_SECRET)."
            ),
            pit_safe=False,
        )

    if not live:
        return ProviderProbeResult(
            provider=SOURCE_EDISCLOSURE_GATEWAY,
            configured=True,
            enabled=True,
            reachable=None,
            authenticated=None,
            operational_status=ProviderOperationalStatus.READY_REQUIRES_CREDENTIALS,
            pit_capability="DISCLOSURE_EVENTS",
            timestamp_quality=TimestampQuality.EXACT_TIMESTAMP,
            access_model=AccessModel.CREDENTIALS_REQUIRED,
            last_successful_request=None,
            human_explanation=(
                "Учётные данные заданы; live-проверка не выполнялась в этом запросе."
            ),
            pit_safe=False,
        )

    gateway = client or EdisclosureGatewayClient(settings=settings)
    try:
        gateway.authenticate(
            AuthParams(
                login=settings.edisclosure_gateway_username.strip(),
                password=settings.edisclosure_gateway_secret,
            )
        )
        gateway.fetch_message_types()
        now = datetime.now(UTC).isoformat()
        return ProviderProbeResult(
            provider=SOURCE_EDISCLOSURE_GATEWAY,
            configured=True,
            enabled=True,
            reachable=True,
            authenticated=True,
            operational_status=ProviderOperationalStatus.READY,
            pit_capability="DISCLOSURE_EVENTS",
            timestamp_quality=TimestampQuality.EXACT_TIMESTAMP,
            access_model=AccessModel.CREDENTIALS_REQUIRED,
            last_successful_request=now,
            human_explanation="Авторизация шлюза успешна; eventDate используется как known_at.",
            pit_safe=True,
        )
    except httpx.HTTPStatusError as exc:
        body: str | dict[str, Any] | None
        try:
            body = exc.response.json()
        except Exception:
            body = exc.response.text
        msg = humanize_auth_failure(exc.response.status_code, body)
        status = (
            ProviderOperationalStatus.READY_REQUIRES_SUBSCRIPTION
            if exc.response.status_code == 403
            else ProviderOperationalStatus.DEGRADED
        )
        return ProviderProbeResult(
            provider=SOURCE_EDISCLOSURE_GATEWAY,
            configured=True,
            enabled=True,
            reachable=True,
            authenticated=False,
            operational_status=status,
            pit_capability="DISCLOSURE_EVENTS",
            timestamp_quality=TimestampQuality.EXACT_TIMESTAMP,
            access_model=AccessModel.CREDENTIALS_REQUIRED,
            last_successful_request=None,
            human_explanation=msg,
            pit_safe=False,
        )
    except Exception as exc:
        return ProviderProbeResult(
            provider=SOURCE_EDISCLOSURE_GATEWAY,
            configured=True,
            enabled=True,
            reachable=False,
            authenticated=False,
            operational_status=ProviderOperationalStatus.DEGRADED,
            pit_capability="DISCLOSURE_EVENTS",
            timestamp_quality=TimestampQuality.EXACT_TIMESTAMP,
            access_model=AccessModel.CREDENTIALS_REQUIRED,
            last_successful_request=None,
            human_explanation=redact_secrets(str(exc)),
            pit_safe=False,
        )
    finally:
        if client is None:
            gateway.close()


def probe_gir_bo(
    *,
    settings: Settings | None = None,
    client: GirBoClient | None = None,
    live: bool = False,
) -> ProviderProbeResult:
    settings = settings or get_settings()
    classification = classify_gir_bo_access(enabled=settings.gir_bo_enabled)
    if not settings.gir_bo_enabled:
        return ProviderProbeResult(
            provider=SOURCE_GIR_BO,
            configured=False,
            enabled=False,
            reachable=None,
            authenticated=None,
            operational_status=ProviderOperationalStatus.READY,
            pit_capability="RAS_BFO_PARTIAL",
            timestamp_quality=TimestampQuality.DATE_ONLY,
            access_model=AccessModel.PUBLIC_API,
            last_successful_request=None,
            human_explanation=(
                "ГИР БО: публичный JSON (поиск по ИНН, список БФО, формы РСБУ в typeCorrections) "
                "доступен; known_at только DATE_ONLY (actualBfoDate). Адаптер выключен "
                "(GIR_BO_ENABLED=false). Массовая подписка — отдельно."
            ),
            pit_safe=False,
        )

    if not live:
        return ProviderProbeResult(
            provider=SOURCE_GIR_BO,
            configured=True,
            enabled=True,
            reachable=None,
            authenticated=True,
            operational_status=ProviderOperationalStatus.READY,
            pit_capability="RAS_BFO_PARTIAL",
            timestamp_quality=TimestampQuality.DATE_ONLY,
            access_model=classification.access_model,
            last_successful_request=None,
            human_explanation=classification.note,
            pit_safe=False,
        )

    gir = client or GirBoClient(settings=settings)
    try:
        probe = gir.sample_probe()
        reachable = bool(probe.get("reachable"))
        last_ok = datetime.now(UTC).isoformat() if reachable else None
        op_status = (
            ProviderOperationalStatus.READY
            if reachable
            else ProviderOperationalStatus.DEGRADED
        )
        if probe.get("error") and "подписк" in str(probe.get("error")).lower():
            op_status = ProviderOperationalStatus.READY_REQUIRES_SUBSCRIPTION
        return ProviderProbeResult(
            provider=SOURCE_GIR_BO,
            configured=True,
            enabled=True,
            reachable=reachable,
            authenticated=probe.get("authenticated"),
            operational_status=op_status,
            pit_capability="RAS_BFO_PARTIAL",
            timestamp_quality=TimestampQuality.DATE_ONLY,
            access_model=classification.access_model,
            last_successful_request=last_ok,
            human_explanation=str(probe.get("error") or classification.note),
            pit_safe=False,
        )
    except httpx.HTTPStatusError as exc:
        return ProviderProbeResult(
            provider=SOURCE_GIR_BO,
            configured=True,
            enabled=True,
            reachable=False,
            authenticated=exc.response.status_code not in {401, 403},
            operational_status=ProviderOperationalStatus.READY_REQUIRES_SUBSCRIPTION
            if exc.response.status_code in {402, 403}
            else ProviderOperationalStatus.DEGRADED,
            pit_capability="RAS_BFO_PARTIAL",
            timestamp_quality=TimestampQuality.DATE_ONLY,
            access_model=AccessModel.PAID_SUBSCRIPTION
            if exc.response.status_code in {402, 403}
            else classification.access_model,
            last_successful_request=None,
            human_explanation=subscription_required_message(exc.response.status_code),
            pit_safe=False,
        )
    finally:
        if client is None:
            gir.close()


def probe_all_providers(*, live: bool = False) -> list[ProviderProbeResult]:
    settings = get_settings()
    return [
        _moex_status(settings),
        probe_edisclosure_gateway(settings=settings, live=live),
        probe_gir_bo(settings=settings, live=live),
    ]


def provider_probe_to_dict(result: ProviderProbeResult) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "configured": result.configured,
        "enabled": result.enabled,
        "reachable": result.reachable,
        "authenticated": result.authenticated,
        "operational_status": result.operational_status.value,
        "pit_capability": result.pit_capability,
        "timestamp_quality": result.timestamp_quality.value,
        "access_model": result.access_model.value,
        "last_successful_request": result.last_successful_request,
        "human_explanation": result.human_explanation,
        "pit_safe": result.pit_safe,
    }
