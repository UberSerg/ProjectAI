#!/usr/bin/env python3
"""Local Vault integrity checks. No network. No secrets scan beyond simple patterns."""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"E:\kraken Vault")
ID_RE = re.compile(r"\bid:\s*(KRK-[A-Z]+-\d{4})\b")
WIKI_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key\s*[:=]\s*\S+|secret\s*[:=]\s*\S+|Bearer\s+[A-Za-z0-9\-._~+/]+=*|password\s*[:=]\s*\S+)"
)
ALLOWED_TASK_STATUS = {
    "idea",
    "proposed",
    "approved",
    "ready",
    "in_progress",
    "blocked",
    "in_review",
    "ready_for_owner_review",
    "accepted",
    "merged",
    "released",
    "deferred",
    "cancelled",
}


def md_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.md") if ".obsidian" not in p.parts]


def note_names() -> set[str]:
    return {p.stem for p in md_files()}


def main() -> int:
    files = md_files()
    names = note_names()
    ids: list[str] = []
    broken_links: list[str] = []
    secret_hits: list[str] = []
    status_issues: list[str] = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        ids.extend(ID_RE.findall(text))
        for m in WIKI_RE.finditer(text):
            target = m.group(1).strip()
            # allow path-like wikilinks by stem
            stem = Path(target).stem
            if stem not in names and target not in names:
                broken_links.append(f"{path.relative_to(ROOT)} -> [[{target}]]")
        for m in SECRET_RE.finditer(text):
            secret_hits.append(f"{path.relative_to(ROOT)}: {m.group(0)[:40]}…")
        if path.parts and ("06-БЭКЛОГ" in path.parts or "05-КАТАЛОГ ПРОБЛЕМ" in path.parts):
            for sm in re.finditer(r"(?m)^status:\s*(\S+)", text):
                st = sm.group(1).strip()
                if "БЭКЛОГ" in str(path) and st not in ALLOWED_TASK_STATUS and not st.startswith("open"):
                    # problems use different status set; only warn on tasks folder
                    if "Технические задачи" in path.parts or "Эпики" in path.parts or "Возможности" in path.parts:
                        if st not in ALLOWED_TASK_STATUS:
                            status_issues.append(f"{path.name}: status={st}")

    id_counts = Counter(ids)
    dup_ids = sorted([i for i, c in id_counts.items() if c > 1])

    report = []
    report.append(f"# Vault check {ROOT}")
    report.append(f"Markdown files: {len(files)}")
    report.append(f"Unique KRK IDs: {len(id_counts)}")
    report.append(f"Duplicate IDs: {len(dup_ids)}")
    for i in dup_ids:
        report.append(f"  - {i} x{id_counts[i]}")
    report.append(f"Broken wikilinks (stem miss): {len(broken_links)}")
    for b in broken_links[:50]:
        report.append(f"  - {b}")
    if len(broken_links) > 50:
        report.append(f"  … +{len(broken_links) - 50} more")
    report.append(f"Secret-like hits: {len(secret_hits)}")
    for s in secret_hits[:20]:
        report.append(f"  - {s}")
    report.append(f"Status anomalies: {len(status_issues)}")
    for s in status_issues[:30]:
        report.append(f"  - {s}")

    out = ROOT / "_meta" / "QA" / "check_vault_last_run.txt"
    out.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    return 1 if dup_ids or secret_hits else 0


if __name__ == "__main__":
    sys.exit(main())
