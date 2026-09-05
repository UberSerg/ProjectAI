"""Provider matrix for API / CLI / UI."""

from __future__ import annotations

from typing import Any

from app.modules.fundamentals.application.provider_status import (
    probe_all_providers,
    provider_probe_to_dict,
)
from app.modules.fundamentals.domain.types import (
    SOURCE_EDISCLOSURE_GATEWAY,
    SOURCE_GIR_BO,
    SOURCE_MOEX_ISS,
)

_PROVIDER_LABELS: dict[str, dict[str, str]] = {
    SOURCE_MOEX_ISS: {
        "code": SOURCE_MOEX_ISS,
        "name": "MOEX ISS",
        "name_ru": "MOEX ISS",
    },
    SOURCE_EDISCLOSURE_GATEWAY: {
        "code": SOURCE_EDISCLOSURE_GATEWAY,
        "name": "Interfax e-disclosure Gateway",
        "name_ru": "Интерфакс шлюз (e-disclosure Gateway)",
    },
    SOURCE_GIR_BO: {
        "code": SOURCE_GIR_BO,
        "name": "GIR BO",
        "name_ru": "ГИР БО (bo.nalog.gov.ru)",
    },
}


def build_providers_matrix(*, live: bool = False) -> dict[str, Any]:
    rows = []
    for probe in probe_all_providers(live=live):
        labels = _PROVIDER_LABELS.get(probe.provider, {"code": probe.provider, "name": probe.provider})
        rows.append(
            {
                **provider_probe_to_dict(probe),
                **labels,
                "status": probe.operational_status.value,
                "note": probe.human_explanation,
            }
        )
    return {
        "providers": rows,
        "human_summary": (
            "MOEX ISS работает для идентичности; шлюз e-disclosure требует доступа по договору; "
            "ГИР БО даёт частичный публичный доступ к БФО с датой без времени."
        ),
    }


def providers_for_summary(*, live: bool = False) -> list[dict[str, Any]]:
    matrix = build_providers_matrix(live=live)
    items: list[dict[str, Any]] = []
    for row in matrix["providers"]:
        items.append(
            {
                "code": row.get("code"),
                "name": row.get("name_ru") or row.get("name"),
                "status": row.get("status"),
                "note": row.get("note"),
                "deferred": row.get("operational_status")
                in {
                    "UNAVAILABLE",
                    "READY_REQUIRES_CREDENTIALS",
                    "READY_REQUIRES_SUBSCRIPTION",
                },
            }
        )
    return items
