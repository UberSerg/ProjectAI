# -*- coding: utf-8 -*-
"""Final selective illustration pass — only high-value notes."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(r"E:\kraken Vault")
ASSETS = ROOT / "_assets" / "illustrations"
SRC = Path(
    r"C:\Users\AdminV\.cursor\projects\e-AI-ProjectAI-wt-ux-decision-journal\assets"
)

# copy new assets
for name in [
    "frontend-backend",
    "git-worktrees",
    "definition-of-done",
    "stale-docker-mount",
    "zavisimosti-etapov",
    "otlozheno-bez-owner",
    "istoriya-versiy",
    "kriticheskie-problemy",
    "dva-portfelya",
]:
    src = SRC / f"{name}.jpg"
    if src.exists():
        shutil.copy2(src, ASSETS / f"{name}.jpg")

MAP = {
    r"02-АРХИТЕКТУРА\Модули\Frontend.md": (
        "frontend-backend.jpg",
        "Frontend",
        "React/Vite кабинет поверх /api/v1.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Backend API.md": (
        "frontend-backend.jpg",
        "Backend API",
        "FastAPI как единая точка REST.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Инфраструктура.md": (
        "docker-servisy.jpg",
        "Инфраструктура",
        "Docker-first контур сервисов.",
    ),
    r"11-РАЗРАБОТЧИКАМ\Git и worktrees.md": (
        "git-worktrees.jpg",
        "Git и worktrees",
        "Изоляция веток, чужие деревья не трогать.",
    ),
    r"11-РАЗРАБОТЧИКАМ\Definition of Done.md": (
        "definition-of-done.jpg",
        "Definition of Done",
        "Код, тесты, PR, контекст, Vault.",
    ),
    r"11-РАЗРАБОТЧИКАМ\Как устроен код.md": (
        "sloi-arhitektury.jpg",
        "Как устроен код",
        "Слои modular monolith.",
    ),
    r"11-РАЗРАБОТЧИКАМ\Правила безопасности.md": (
        "otlozheno-bez-owner.jpg",
        "Правила безопасности",
        "Секреты, сеть и автономия — только с Owner.",
    ),
    r"09-ПРОБЛЕМЫ И АНТИПАТТЕРНЫ\Устаревший Docker mount.md": (
        "stale-docker-mount.jpg",
        "Устаревший Docker mount",
        "Контейнер может смотреть не на main.",
    ),
    r"07-ПЛАНИРОВАНИЕ\Зависимости этапов.md": (
        "zavisimosti-etapov.jpg",
        "Зависимости этапов",
        "Порядок волн до decision P&L.",
    ),
    r"07-ПЛАНИРОВАНИЕ\План текущего этапа.md": (
        "zavisimosti-etapov.jpg",
        "План текущего этапа",
        "Сначала journal/mount, потом ledger.",
    ),
    r"08-БУДУЩЕЕ KRAKEN\Отложенные идеи.md": (
        "otlozheno-bez-owner.jpg",
        "Отложенные идеи",
        "Без явного Owner — не стартовать.",
    ),
    r"08-БУДУЩЕЕ KRAKEN\Возможные модули.md": (
        "otlozheno-bez-owner.jpg",
        "Возможные модули",
        "Идеи ≠ разрешение на реализацию.",
    ),
    r"06-БЭКЛОГ\Следующее.md": (
        "gorizonty-backlog.jpg",
        "Следующее",
        "После текущего горизонта.",
    ),
    r"06-БЭКЛОГ\Позже.md": (
        "otlozheno-bez-owner.jpg",
        "Позже",
        "Ценность есть, старт не разрешён.",
    ),
    r"06-БЭКЛОГ\Заблокировано.md": (
        "otlozheno-bez-owner.jpg",
        "Заблокировано",
        "Ждём зависимость или решение Owner.",
    ),
    r"05-КАТАЛОГ ПРОБЛЕМ\Критические проблемы.md": (
        "kriticheskie-problemy.jpg",
        "Критические проблемы",
        "P0 блокеры приёмки и честности UI.",
    ),
    r"04-ИСТОРИЯ РАЗРАБОТКИ\История версий.md": (
        "istoriya-versiy.jpg",
        "История версий",
        "Техн. 1.0.0 и продукт 1.01–1.05.",
    ),
    r"04-ИСТОРИЯ РАЗРАБОТКИ\Ключевые этапы.md": (
        "hronologiya-kraken.jpg",
        "Ключевые этапы",
        "Крупные эпохи разработки.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — два личных портфеля.md": (
        "dva-portfelya.jpg",
        "Два личных портфеля",
        "Книги раздельно, Shadow не смешивать.",
    ),
}


def insert(note: Path, img: str, alt: str, caption: str) -> str:
    text = note.read_text(encoding="utf-8")
    if img in text or "Визуальный ориентир" in text[:1200]:
        return "skip"
    rel_img = Path(os.path.relpath(ASSETS / img, start=note.parent)).as_posix()
    block = (
        "\n## Визуальный ориентир\n\n"
        f"![{alt}]({rel_img})\n\n"
        f"*{caption} Иллюстрация Vault.*\n"
    )
    lines = text.splitlines(keepends=True)
    i = 0
    if lines and lines[0].startswith("---"):
        i = 1
        while i < len(lines) and not lines[i].startswith("---"):
            i += 1
        if i < len(lines):
            i += 1
        while i < len(lines) and lines[i].strip() == "":
            i += 1
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    if i >= len(lines):
        return "no_h1"
    i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    note.write_text("".join(lines[:i]) + block + "\n" + "".join(lines[i:]), encoding="utf-8")
    return "ok"


def main() -> None:
    ok = skip = miss = 0
    for rel, (img, alt, cap) in MAP.items():
        note = ROOT / rel
        if not note.exists() or not (ASSETS / img).exists():
            print("MISS", rel, img)
            miss += 1
            continue
        r = insert(note, img, alt, cap)
        print(r.upper(), rel)
        ok += r == "ok"
        skip += r == "skip"
    # policy note
    policy = ASSETS / "README.md"
    extra = (
        "\n## Политика (финал)\n\n"
        "Картинки только там, где схема реально помогает войти в тему. "
        "Не иллюстрировать каждую карточку бага/задачи/события.\n"
    )
    t = policy.read_text(encoding="utf-8")
    if "Политика (финал)" not in t:
        policy.write_text(t.rstrip() + "\n" + extra, encoding="utf-8")
    print(f"ok={ok} skip={skip} miss={miss}")


if __name__ == "__main__":
    main()
