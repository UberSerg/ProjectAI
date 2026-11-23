# Git-размещение Vault

**Статус:** `ACTIVE` (Owner 2026-11-23)  
**Место:** тот же репозиторий `UberSerg/ProjectAI`, каталог `knowledge-vault/`  
**Не** отдельный remote (решение Owner: жить рядом с кодом).

## Канон

| Что | Где |
|---|---|
| Файлы Vault | `knowledge-vault/` на GitHub |
| Локальная работа | клон/worktree → открыть `knowledge-vault/` в Obsidian |
| Опциональный ярлык | `E:\kraken Vault` = junction на `…/knowledge-vault` |

## Workflow

### В начале сессии / задачи

```text
git fetch origin
# обновить свою ветку от main / подтянуть remote
```

Если коллега запушил правки в `knowledge-vault/` — они должны оказаться у вас **до** правок заметок.

### После значимого изменения в Kraken

1. Обновить соответствующие заметки Vault (история / модуль / проблема / задача / roadmap).
2. Commit + **push** (в feature PR или `docs(vault): …`).
3. Не оставлять актуальные знания только на диске.

### Чего не делать

- Вторая расходящаяся копия «просто на E:\» без git
- Секреты и персональные ledger dumps
- Объявлять merge/acceptance только по тексту заметки

## Связанные правила

- `.cursor/rules/45-knowledge-vault.mdc`
- `00-ГЛАВНАЯ/Источники истины.md`
- `docs/development/CHATGPT_MASTER_CONTEXT.md` (статус проекта)
