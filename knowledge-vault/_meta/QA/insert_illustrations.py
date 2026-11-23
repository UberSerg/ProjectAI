# -*- coding: utf-8 -*-
"""Insert Vault illustrations into priority notes."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(r"E:\kraken Vault")
ASSETS = ROOT / "_assets" / "illustrations"

MAP: dict[str, tuple[str, str, str]] = {
    r"00-ГЛАВНАЯ\ДОМ.md": (
        "vault-dom-navigaciya.jpg",
        "Навигация KRAKEN Vault",
        "Карта входа в базу знаний.",
    ),
    r"01-ПРОДУКТ\Что такое Kraken.md": (
        "chto-takoe-kraken.jpg",
        "Что такое Kraken",
        "Аналитический кабинет, не брокерский робот.",
    ),
    r"01-ПРОДУКТ\Personal vs Shadow vs Research.md": (
        "tri-knigi-uchet.jpg",
        "Три книги учёта",
        "Личный, Shadow и Research не смешиваются.",
    ),
    r"01-ПРОДУКТ\Kraken сегодня.md": (
        "kraken-segodnya.jpg",
        "Kraken сегодня",
        "Что уже есть, что частично, чего нет.",
    ),
    r"02-АРХИТЕКТУРА\Слои архитектуры.md": (
        "sloi-arhitektury.jpg",
        "Слои архитектуры",
        "API → Application → Domain → Infrastructure.",
    ),
    r"02-АРХИТЕКТУРА\Потоки данных.md": (
        "potoki-dannyh.jpg",
        "Потоки данных",
        "Рынок, личный журнал, Shadow и Research — разные контуры.",
    ),
    r"02-АРХИТЕКТУРА\Docker и сервисы.md": (
        "docker-servisy.jpg",
        "Docker-сервисы",
        "Локальный compose-контур Kraken.",
    ),
    r"02-АРХИТЕКТУРА\Архитектурные принципы.md": (
        "invarianty-principy.jpg",
        "Архитектурные инварианты",
        "Жёсткие правила корректности.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Shadow-портфель.md": (
        "shadow-portfel.jpg",
        "Shadow-портфель",
        "Сигнал → решение → заявка → исполнение → NAV.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Персональный портфель.md": (
        "lichnyy-portfel.jpg",
        "Личный портфель",
        "Журнал операций → проекция → оценка → UI.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Журнал решений.md": (
        "zhurnal-resheniy.jpg",
        "Журнал решений",
        "День фактов без выдуманного P&L.",
    ),
    r"03-ТЕРМИНЫ\Время и достоверность\Point-in-Time (PIT).md": (
        "point-in-time.jpg",
        "Point-in-Time",
        "Только данные, известные к моменту t.",
    ),
    r"03-ТЕРМИНЫ\Инвестиционные решения\Decision vs Order vs Fill.md": (
        "reshenie-zayavka-fill.jpg",
        "Решение, заявка, исполнение",
        "Три разные сущности.",
    ),
    r"03-ТЕРМИНЫ\Финансовая математика\Missing price ≠ zero.md": (
        "net-ceny-ne-nol.jpg",
        "Нет цены ≠ ноль",
        "Неизвестное нельзя подменять нулём.",
    ),
    r"03-ТЕРМИНЫ\Финансовая математика\NAV и Partial NAV.md": (
        "nav-polnyy-chastichnyy.jpg",
        "Полный и частичный NAV",
        "Частичное не выдавать за полное.",
    ),
    r"03-ТЕРМИНЫ\Время и достоверность\Look-ahead leakage.md": (
        "look-ahead.jpg",
        "Look-ahead",
        "Запрет подглядывания в будущее.",
    ),
    r"03-ТЕРМИНЫ\Машинное обучение\Walk-forward.md": (
        "walk-forward.jpg",
        "Walk-forward",
        "Обучение на прошлом, проверка на будущем.",
    ),
    r"03-ТЕРМИНЫ\Инвестиционные решения\Candidate vs Champion.md": (
        "candidate-champion.jpg",
        "Candidate vs Champion",
        "Промоушен только после проверки.",
    ),
    r"03-ТЕРМИНЫ\Время и достоверность\known_at vs effective_date.md": (
        "known-at-effective.jpg",
        "known_at и effective_date",
        "Узнали ≠ экономическая дата.",
    ),
    r"03-ТЕРМИНЫ\Разработка и инфраструктура\USER vs OWNER mode.md": (
        "user-owner-mode.jpg",
        "USER и OWNER",
        "Режимы UI, не IAM.",
    ),
    r"03-ТЕРМИНЫ\Финансовая математика\Cost basis.md": (
        "sebestoimost-pnl.jpg",
        "Себестоимость",
        "Реализованный и нереализованный P&L раздельно.",
    ),
    r"03-ТЕРМИНЫ\Финансовая математика\Realized vs Unrealized P&L.md": (
        "sebestoimost-pnl.jpg",
        "Реализованный и нереализованный P&L",
        "Считать раздельно, не смешивать с депозитом.",
    ),
    r"03-ТЕРМИНЫ\Рынок и данные\MOEX EOD.md": (
        "moex-eod.jpg",
        "MOEX EOD",
        "Дневные свечи и watermark дня.",
    ),
    r"04-ИСТОРИЯ РАЗРАБОТКИ\Хронология Kraken.md": (
        "hronologiya-kraken.jpg",
        "Хронология Kraken",
        "Крупные эпохи 2026.",
    ),
    r"05-КАТАЛОГ ПРОБЛЕМ\Все проблемы.md": (
        "katalog-problem.jpg",
        "Каталог проблем",
        "Ошибки, риски и долг.",
    ),
    r"06-БЭКЛОГ\Сейчас.md": (
        "gorizonty-backlog.jpg",
        "Горизонты работ",
        "Сейчас / следующее / позже.",
    ),
    r"07-ПЛАНИРОВАНИЕ\Roadmap Kraken.md": (
        "roadmap-gates.jpg",
        "Roadmap Gates",
        "Ступени без импорта брокера.",
    ),
    r"08-БУДУЩЕЕ KRAKEN\Автономность и ограничения.md": (
        "granicy-avtonomii.jpg",
        "Границы автономии",
        "Что нельзя без Owner.",
    ),
    r"09-ПРОБЛЕМЫ И АНТИПАТТЕРНЫ\Индекс антипаттернов.md": (
        "antipatterny.jpg",
        "Антипаттерны",
        "Типовые ловушки проекта.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Индекс сценариев.md": (
        "scenarii-praktika.jpg",
        "Практические сценарии",
        "Сюжеты для погружения.",
    ),
    r"11-РАЗРАБОТЧИКАМ\Первый день разработчика.md": (
        "pervyy-den-razrab.jpg",
        "Первый день разработчика",
        "Безопасный старт.",
    ),
}


def main() -> None:
    inserted = skipped = missing = 0
    for rel, (img, alt, caption) in MAP.items():
        note = ROOT / rel
        if not note.exists():
            print("MISS_NOTE", rel)
            missing += 1
            continue
        text = note.read_text(encoding="utf-8")
        marker = f"/_assets/illustrations/{img})"
        if marker in text.replace("\\", "/"):
            skipped += 1
            continue
        rel_img = Path(os.path.relpath(ASSETS / img, start=note.parent)).as_posix()
        block = (
            "\n## Визуальный ориентир\n\n"
            f"![{alt}]({rel_img})\n\n"
            f"*{caption} Иллюстрация Vault; не скриншот приёмки и не доказательство runtime.*\n"
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
            print("NO_H1", rel)
            continue
        i += 1
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        # skip if visual section already exists next
        if i < len(lines) and "Визуальный ориентир" in lines[i]:
            skipped += 1
            continue
        new_text = "".join(lines[:i]) + block + "\n" + "".join(lines[i:])
        note.write_text(new_text, encoding="utf-8")
        inserted += 1
        print("OK", rel)
    print(f"inserted={inserted} skipped={skipped} missing={missing}")


if __name__ == "__main__":
    main()
