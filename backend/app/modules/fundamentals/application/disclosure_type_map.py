"""Message-type id → candidate category mapping for e-disclosure Gateway.

Unknown types stay SOURCE_ONLY — no fuzzy name matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.fundamentals.domain.types import NormalizationStatus


class DisclosureCategory(StrEnum):
    FINANCIAL_REPORT = "FINANCIAL_REPORT"
    DIVIDEND = "DIVIDEND"
    MATERIAL_FACT = "MATERIAL_FACT"
    GOVERNANCE = "GOVERNANCE"
    OTHER = "OTHER"
    SOURCE_ONLY = "SOURCE_ONLY"


@dataclass(frozen=True, slots=True)
class MessageTypeMapping:
    message_type_id: int
    message_type_name: str
    category: DisclosureCategory
    normalization_status: NormalizationStatus


# Pin only audited dictionary ids. Extend when Interfax dictionary is loaded with credentials.
MESSAGE_TYPE_MAP: dict[int, DisclosureCategory] = {
    # Placeholder ids — real ids must come from /dictionaries/message-types after auth.
    # Unknown ids always map to SOURCE_ONLY at runtime.
}


def map_message_type(type_id: int | None, type_name: str | None = None) -> MessageTypeMapping:
    if type_id is None:
        return MessageTypeMapping(
            message_type_id=-1,
            message_type_name=type_name or "",
            category=DisclosureCategory.SOURCE_ONLY,
            normalization_status=NormalizationStatus.SOURCE_ONLY,
        )
    category = MESSAGE_TYPE_MAP.get(int(type_id), DisclosureCategory.SOURCE_ONLY)
    status = (
        NormalizationStatus.NORMALIZED
        if category is not DisclosureCategory.SOURCE_ONLY
        else NormalizationStatus.SOURCE_ONLY
    )
    return MessageTypeMapping(
        message_type_id=int(type_id),
        message_type_name=type_name or "",
        category=category,
        normalization_status=status,
    )


def register_message_types(rows: list[dict]) -> dict[int, DisclosureCategory]:
    """Merge authenticated dictionary rows without fuzzy mapping by name."""
    merged = dict(MESSAGE_TYPE_MAP)
    for row in rows:
        type_id = row.get("id")
        if type_id is None:
            continue
        if int(type_id) not in merged:
            merged[int(type_id)] = DisclosureCategory.SOURCE_ONLY
    return merged
