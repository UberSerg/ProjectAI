"""CBR credit-organisation form catalog helpers (coverage only, no metric values).

Parses public HTML reports index links such as:
``/banking_sector/credit/coinfo/f101?regnum=1481&dt=2026-09-01``

Does **not** scrape table cells into financial metrics. Coverage metadata is
PARTIAL evidence that bank forms exist; metric readiness remains NOT_AVAILABLE.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import unquote

_FORM_HREF_RE = re.compile(
    r"""href=["'](?P<href>[^"']*/(?:f101|f102|f123|f135)\?[^"']+)["']""",
    re.IGNORECASE,
)
_FORM_QUERY_RE = re.compile(
    r"""/(?P<form>f101|f102|f123|f135)\?regnum=(?P<regnum>\d+)(?:&|&amp;)dt=(?P<dt>\d{4}-\d{2}-\d{2})""",
    re.IGNORECASE,
)

CBR_REPORTS_URL_TMPL = "https://www.cbr.ru/finorg/foinfo/reports/?ogrn={ogrn}"
CBR_FORM_URL_TMPL = (
    "https://www.cbr.ru/banking_sector/credit/coinfo/{form}?regnum={regnum}&dt={dt}"
)


@dataclass(frozen=True, slots=True)
class CbrFormCoverage:
    form: str
    regnum: str
    dates: tuple[str, ...]
    min_dt: str | None
    max_dt: str | None
    count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CbrCatalogIndex:
    ogrn: str
    regnum: str | None
    forms: tuple[CbrFormCoverage, ...]
    source_url: str
    status: str = "PARTIAL"
    limitations: tuple[str, ...] = (
        "html_index_only",
        "metrics_not_extracted",
        "known_at_not_established",
    )
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ogrn": self.ogrn,
            "regnum": self.regnum,
            "forms": [f.to_dict() for f in self.forms],
            "source_url": self.source_url,
            "status": self.status,
            "limitations": list(self.limitations),
            "extra": dict(self.extra),
        }


def parse_cbr_reports_index_html(
    html: str,
    *,
    ogrn: str,
    source_url: str | None = None,
) -> CbrCatalogIndex:
    """Pure parser: extract form/date coverage from CBR reports HTML."""
    by_form: dict[str, set[str]] = {}
    regnums: set[str] = set()
    for match in _FORM_HREF_RE.finditer(html or ""):
        href = unquote(match.group("href").replace("&amp;", "&"))
        qm = _FORM_QUERY_RE.search(href)
        if not qm:
            continue
        form = qm.group("form").lower()
        regnum = qm.group("regnum")
        dt = qm.group("dt")
        regnums.add(regnum)
        by_form.setdefault(form, set()).add(dt)

    forms: list[CbrFormCoverage] = []
    for form in sorted(by_form):
        dates = tuple(sorted(by_form[form]))
        forms.append(
            CbrFormCoverage(
                form=form,
                regnum=sorted(regnums)[0] if len(regnums) == 1 else ",".join(sorted(regnums)),
                dates=dates,
                min_dt=dates[0] if dates else None,
                max_dt=dates[-1] if dates else None,
                count=len(dates),
            )
        )

    regnum: str | None
    if len(regnums) == 1:
        regnum = next(iter(regnums))
    elif not regnums:
        regnum = None
    else:
        regnum = None

    status = "PARTIAL" if forms else "NOT_AVAILABLE"
    return CbrCatalogIndex(
        ogrn=ogrn,
        regnum=regnum,
        forms=tuple(forms),
        source_url=source_url or CBR_REPORTS_URL_TMPL.format(ogrn=ogrn),
        status=status,
        extra={"distinct_regnums": sorted(regnums)},
    )


def fetch_cbr_reports_index_html(
    ogrn: str,
    *,
    timeout_s: float = 25.0,
    user_agent: str = "ProjectAI-Kraken-Intelligence/1.0 (+bank fundamentals audit)",
) -> str:
    """Optional live fetch for smoke/ops. Tests must use fixtures instead."""
    import httpx

    url = CBR_REPORTS_URL_TMPL.format(ogrn=ogrn)
    with httpx.Client(
        timeout=timeout_s,
        headers={"User-Agent": user_agent, "Accept": "text/html"},
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text
