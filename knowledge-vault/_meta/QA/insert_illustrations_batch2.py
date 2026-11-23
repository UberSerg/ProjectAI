# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(r"E:\kraken Vault")
ASSETS = ROOT / "_assets" / "illustrations"

MAP: dict[str, tuple[str, str, str]] = {
    r"00-ГЛАВНАЯ\Источники истины.md": (
        "istochniki-istiny.jpg",
        "Источники истины",
        "GitHub → Master Context → Vault.",
    ),
    r"00-ГЛАВНАЯ\Как пользоваться Vault.md": (
        "kak-chitat-vault.jpg",
        "Как читать Vault",
        "ДОМ → раздел → сверка с GitHub.",
    ),
    r"00-ГЛАВНАЯ\Глоссарий.md": (
        "glossariy.jpg",
        "Глоссарий",
        "Один термин — одна заметка.",
    ),
    r"00-ГЛАВНАЯ\Навигация по проекту.md": (
        "vault-dom-navigaciya.jpg",
        "Навигация по проекту",
        "Карта разделов Vault.",
    ),
    r"01-ПРОДУКТ\Зачем существует Kraken.md": (
        "zachem-kraken.jpg",
        "Зачем Kraken",
        "Понять, проверить, накапливать evidence.",
    ),
    r"01-ПРОДУКТ\Конкурентное позиционирование.md": (
        "snowball-bez-brokera.jpg",
        "Snowball без брокера",
        "Паритет UX без импорта счёта.",
    ),
    r"01-ПРОДУКТ\Что пока не реализовано.md": (
        "chto-eshche-net.jpg",
        "Что ещё нет",
        "Честный список пробелов.",
    ),
    r"01-ПРОДУКТ\Основные возможности.md": (
        "osnovnye-vozmozhnosti.jpg",
        "Основные возможности",
        "По main, без обещания прибыли.",
    ),
    r"01-ПРОДУКТ\Kraken в будущем.md": (
        "idealnyy-kraken.jpg",
        "Kraken в будущем",
        "Цель, не факт сегодня.",
    ),
    r"01-ПРОДУКТ\Пользовательские сценарии.md": (
        "scenarii-praktika.jpg",
        "Пользовательские сценарии",
        "Сюжеты инвестора.",
    ),
    r"02-АРХИТЕКТУРА\Хранилища.md": (
        "hranilishcha.jpg",
        "Хранилища",
        "Core, Memory, Redis, raw.",
    ),
    r"02-АРХИТЕКТУРА\Модули.md": (
        "sloi-arhitektury.jpg",
        "Модули",
        "Индекс паспортов системы.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Portfolio Hub.md": (
        "portfolio-hub.jpg",
        "Portfolio Hub",
        "Полная / частичная / недоступна.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Ручной журнал операций.md": (
        "ruchnoy-zhurnal.jpg",
        "Ручной журнал",
        "Append-only операции.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Рыночные данные.md": (
        "rynochnye-dannye.jpg",
        "Рыночные данные",
        "MOEX EOD → сырые свечи.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Память решений.md": (
        "pamyat-resheniy.jpg",
        "Память решений",
        "Отдельная Memory DB.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Датасет.md": (
        "dataset-spec.jpg",
        "Датасет",
        "Активна v1; v2+ research.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Прогноз.md": (
        "prognoz-politika-risk.jpg",
        "Прогноз и контур",
        "Не склеивать роли в одного агента.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Торговая политика.md": (
        "prognoz-politika-risk.jpg",
        "Торговая политика",
        "Отдельно от прогноза и риска.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Риск.md": (
        "prognoz-politika-risk.jpg",
        "Риск",
        "Отдельный контур, не «всё в одном».",
    ),
    r"02-АРХИТЕКТУРА\Модули\Исполнение.md": (
        "prognoz-politika-risk.jpg",
        "Исполнение",
        "Адаптер; брокер не в V1.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Company Intelligence.md": (
        "company-intelligence.jpg",
        "Company Intelligence",
        "Advisory, не приказ брокеру.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Исследования.md": (
        "research-evidence.jpg",
        "Исследования",
        "Evidence research-only.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Исторический симулятор.md": (
        "istoricheskiy-simulyator.jpg",
        "Исторический симулятор",
        "Прогон прошлого, не живой брокер.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Фундаментал.md": (
        "fundamental.jpg",
        "Фундаментал",
        "Учитывать дату публикации.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Дивиденды и корпоративные действия.md": (
        "korporativnye-deystviya.jpg",
        "Корпоративные действия",
        "События отдельно от свечей.",
    ),
    r"02-АРХИТЕКТУРА\Модули\Shadow.md": (
        "shadow-portfel.jpg",
        "Shadow",
        "Указатель на паспорт Shadow-портфеля.",
    ),
    r"03-ТЕРМИНЫ\Время и достоверность\Evidence level.md": (
        "evidence-level.jpg",
        "Evidence level",
        "Не повышать уровень без проверки.",
    ),
    r"03-ТЕРМИНЫ\Рынок и данные\Raw candles.md": (
        "syrie-svechi.jpg",
        "Сырые свечи",
        "RAW OHLCV immutable.",
    ),
    r"03-ТЕРМИНЫ\Рынок и данные\Corporate actions.md": (
        "korporativnye-deystviya.jpg",
        "Корпоративные действия",
        "Событие ≠ ремонт цены.",
    ),
    r"03-ТЕРМИНЫ\Рынок и данные\Total return.md": (
        "total-return.jpg",
        "Total return",
        "Отдельно от RAW свечей.",
    ),
    r"03-ТЕРМИНЫ\Финансовая математика\XIRR.md": (
        "xirr.jpg",
        "XIRR",
        "Доходность денег во времени.",
    ),
    r"03-ТЕРМИНЫ\Финансовая математика\Комиссии и двойной учёт.md": (
        "komissii-dvoynoy-uchet.jpg",
        "Комиссии",
        "Не учитывать дважды.",
    ),
    r"03-ТЕРМИНЫ\Инвестиционные решения\LIVE vs COUNTERFACTUAL_REPLAY.md": (
        "live-vs-replay.jpg",
        "LIVE ≠ REPLAY",
        "Не подменять историю.",
    ),
    r"03-ТЕРМИНЫ\Машинное обучение\Dataset Spec.md": (
        "dataset-spec.jpg",
        "Dataset Spec",
        "Активная спецификация отдельно от research.",
    ),
    r"03-ТЕРМИНЫ\Машинное обучение\Research Evidence Engine.md": (
        "research-evidence.jpg",
        "Research Evidence Engine",
        "Дossier и OOS — research-only.",
    ),
    r"03-ТЕРМИНЫ\Разработка и инфраструктура\Decision Memory DB.md": (
        "pamyat-resheniy.jpg",
        "Decision Memory DB",
        "Отдельная память решений.",
    ),
    r"08-БУДУЩЕЕ KRAKEN\Идеальный Kraken.md": (
        "idealnyy-kraken.jpg",
        "Идеальный Kraken",
        "Целевой образ продукта.",
    ),
    r"09-ПРОБЛЕМЫ И АНТИПАТТЕРНЫ\Двойной учёт комиссий.md": (
        "komissii-dvoynoy-uchet.jpg",
        "Двойные комиссии",
        "Ловушка скрытых потерь.",
    ),
    r"09-ПРОБЛЕМЫ И АНТИПАТТЕРНЫ\Дивиденды, зашитые в свечи.md": (
        "korporativnye-deystviya.jpg",
        "Дивиденды и свечи",
        "Не зашивать дивиденд в RAW.",
    ),
    r"09-ПРОБЛЕМЫ И АНТИПАТТЕРНЫ\Research выдан за production.md": (
        "research-evidence.jpg",
        "Research ≠ production",
        "Не смешивать среды.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — журнал от взноса до частичной продажи.md": (
        "scenariy-pervaya-pokupka.jpg",
        "От взноса до продажи",
        "Базовый путь ручного учёта.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — три даты одного следа.md": (
        "scenariy-tri-daty.jpg",
        "Три даты одного следа",
        "Сигнал / решение / fill раздельно.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — нет цены, оценка частичная.md": (
        "scenariy-net-ceny.jpg",
        "Нет цены",
        "Частичная оценка, не ноль.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — кампания не становится чемпионом.md": (
        "candidate-champion.jpg",
        "Кампания ≠ champion",
        "Research не промоутится сам.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — Shadow не берёт сегодняшний open.md": (
        "shadow-portfel.jpg",
        "Shadow и next session",
        "Исполнение не подглядывает open дня сигнала.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — взнос не является прибылью.md": (
        "sebestoimost-pnl.jpg",
        "Взнос ≠ прибыль",
        "Депозит не считать доходностью.",
    ),
    r"10-ПРАКТИЧЕСКИЕ СЦЕНАРИИ\Сценарий — совет не двигает деньги.md": (
        "company-intelligence.jpg",
        "Совет ≠ исполнение",
        "Рекомендация не двигает брокер.",
    ),
}


def insert(note: Path, img: str, alt: str, caption: str) -> str:
    text = note.read_text(encoding="utf-8")
    if f"/_assets/illustrations/{img})" in text.replace("\\", "/") or "Визуальный ориентир" in text[:800]:
        # allow insert if visual section not present near top; skip if image already
        if img.split(".")[0] in text or f"{img})" in text:
            return "skip"
    rel_img = Path(os.path.relpath(ASSETS / img, start=note.parent)).as_posix()
    block = (
        "\n## Визуальный ориентир\n\n"
        f"![{alt}]({rel_img})\n\n"
        f"*{caption} Иллюстрация Vault; не скриншот приёмки.*\n"
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
    if i < len(lines) and "Визуальный ориентир" in lines[i]:
        return "skip"
    note.write_text("".join(lines[:i]) + block + "\n" + "".join(lines[i:]), encoding="utf-8")
    return "ok"


def main() -> None:
    ok = skip = miss = noh1 = 0
    for rel, (img, alt, cap) in MAP.items():
        note = ROOT / rel
        if not note.exists():
            print("MISS", rel)
            miss += 1
            continue
        if not (ASSETS / img).exists():
            print("NOIMG", img)
            miss += 1
            continue
        r = insert(note, img, alt, cap)
        print(r.upper(), rel)
        if r == "ok":
            ok += 1
        elif r == "skip":
            skip += 1
        else:
            noh1 += 1
    print(f"ok={ok} skip={skip} miss={miss} noh1={noh1}")


if __name__ == "__main__":
    main()
