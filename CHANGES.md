# ARCANE 2 — Changelog: Финальный пакет изменений

## Дата: 5 апреля 2026

---

## 1. SQLite Persistence (`core/persistence.py` + `api/compat_all.py`)

### Проблема
Все данные (`_users`, `_sessions`, `_chats`, `_messages`, `_groups`, `_audit_logs` и др.)
хранились в памяти. При рестарте сервиса — всё терялось.

### Решение
Новый модуль `core/persistence.py`:
- `_KVTable` — generic key→JSON dict, persistent в SQLite
- `_MessagesTable` — сообщения чатов, per-message индексирование
- `_AuditLogTable` — append-only лог с cap 10k и streaming iteration
- `_SSEBus` — in-memory event bus для real-time SSE стриминга

`compat_all.py` теперь использует `get_store()` вместо dict:
```python
_users   = _store.users      # SQLite KVTable
_sessions = _store.sessions  # SQLite KVTable
_chats   = _store.chats      # SQLite KVTable
_messages = _store.messages  # SQLite MessagesTable
```

**БД**: `/root/workspace/.arcane_app.db` (настраивается через `ARCANE_PERSIST_DB` env)

### Совместимость
KVTable реализует полный dict-интерфейс:
- `.get()`, `.set()`, `.delete()`, `.all()`, `.items()`, `.keys()`, `.values()`
- `__getitem__`, `__setitem__`, `__contains__`, `.pop()`, `.setdefault()`

---

## 2. Real-time SSE Streaming (`api/compat_all.py`)

### Проблема
`GET /api/chats/{id}/subscribe` отправлял только pings каждую секунду.
Пользователь не получал события агента (progress, tool calls, cost updates).

### Решение
SSE endpoint теперь подписывается на `_sse_bus` (asyncio.Queue):
- Ожидает события через `asyncio.wait_for(queue.get(), timeout=15.0)`
- Пинг каждые 15 секунд (не каждую секунду)
- Корректно unsubscribes при disconnect

### Источники событий
1. **`send_message`** → публикует в SSE bus при получении ответа LLM
2. **`_broadcast_status`** в `api.py` → публикует в SSE bus при каждом изменении
   статуса задачи оркестратора (`thinking`, `tool_executing`, `cost_update`, etc.)

### Frontend интеграция
Без изменений — frontend уже слушает `/api/chats/{id}/subscribe?token=...`

---

## 3. Rate Limiting (`api/api.py`)

### Добавлено
Класс `_RateLimiter` — sliding window per-key:
```
POST /api/projects/{id}/tasks  →  10 req/min per IP+project
```

- 429 Too Many Requests с заголовком `Retry-After: N`
- Настраивается: `ARCANE_TASK_RATE_LIMIT=10` (env)

### Input validation
- Пустая задача → 400
- Задача > 50,000 символов → 400

### Новый endpoint
```
GET /api/rate-limit/status  →  { limit, window_sec, ip }
```

---

## 4. OAuth 2.0 (`api/compat_all.py`)

### Новые endpoints
```
GET /api/oauth/login?provider=default  →  redirect to provider
GET /api/oauth/callback?code=&state=   →  exchange code, set cookie, redirect /
```

### Конфигурация (environment variables)
```
OAUTH_SERVER_URL=https://your-oauth-provider.com
OAUTH_CLIENT_ID=your-client-id
OAUTH_CLIENT_SECRET=your-client-secret
```

### Поведение
- Если `OAUTH_SERVER_URL` не задан → redirect `/?oauth_error=not_configured`
- Успешный логин → cookie `session_token` (30 дней) + redirect `/`
- Пользователь создаётся/обновляется в SQLite
- Аудит лог: `oauth.login`

---

## 5. Прочие фиксы (из предыдущей сессии, включены в этот архив)

| # | Фикс | Файл |
|---|---|---|
| FIX-1 | 24 admin endpoint без auth → `_check_admin_auth()` добавлен | `compat_all.py` |
| FIX-2 | `snap.get("remaining_usd")` → `_budget_remaining_safe()` | `api.py` |
| FIX-3 | memory_v9 dangerous imports removed (dynamic_tools, finetuning, cross_learning) | `engine.py` |
| FIX-4 | `episodic.py` + `continuity.py` стабы созданы | `memory_v9/` |
| FIX-5 | CRIT-F: `_log_usage_to_db` вызывается для FREE моделей | `agent_loop.py` |

---

## Деплой на сервер

```bash
# 1. Обновить файлы
cd /root/arcane2
git pull  # или rsync архив

# 2. Установить зависимости
pip install fpdf2>=2.8.0 --break-system-packages

# 3. Задать токены в systemd (если ещё не сделано)
sudo systemctl edit arcane2
# Добавить:
# [Service]
# Environment=ARCANE_ADMIN_TOKEN=<openssl rand -hex 32>
# Environment=ARCANE_CROSS_LEARNING=false

# 4. Перезапустить
sudo systemctl daemon-reload
sudo systemctl restart arcane2
sudo systemctl status arcane2
```

**База данных создаётся автоматически** при первом запуске:
`/root/workspace/.arcane_app.db`

---

## Environment Variables (полный список)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `ARCANE_ADMIN_TOKEN` | "" (dev mode) | Admin токен для /api/admin/* |
| `ARCANE_ADMIN_PASSWORD` | "arcane2025" | Пароль для login |
| `ARCANE_PERSIST_DB` | `/root/workspace/.arcane_app.db` | Путь к SQLite |
| `ARCANE_TASK_RATE_LIMIT` | "10" | Max задач/мин per IP |
| `ARCANE_CROSS_LEARNING` | "false" | Включить cross-user learning |
| `ARCANE_WORKSPACE` | "/root/workspace" | Рабочая директория |
| `OPENROUTER_API_KEY` | — | OpenRouter API ключ |
| `OAUTH_SERVER_URL` | "" | OAuth provider URL |
| `OAUTH_CLIENT_ID` | "" | OAuth client ID |
| `OAUTH_CLIENT_SECRET` | "" | OAuth client secret |


---

## 6. Финальные фиксы (этот коммит)

### 6.1 Синтаксические ошибки (admin auth patch)
- Исправлены запятые `async def func(, request)` → `async def func(request)` в 24 admin endpoint
- Исправлена `IndentationError` в `engine.py` после патча DynamicToolManager

### 6.2 Улучшения admin endpoints
- **`/admin/stats`** — теперь возвращает реальные данные: задачи из `history_db`, running tasks из `orchestrator._runs`, стоимость из `budget_controller`
- **`/admin/spending`** — использует `budget_controller.dashboard()` если доступен, иначе fallback на audit_logs

### 6.3 Новые endpoints (ранее отсутствовали полностью)

| Endpoint | Описание |
|---|---|
| `GET /api/memory` | Список memory entries |
| `POST /api/memory/search` | Semantic search (через SemanticMemory) |
| `POST /api/memory` | Добавить memory entry |
| `DELETE /api/memory/:id` | Удалить entry |
| `GET /api/memory/stats` | Статистика memory системы |
| `GET /api/admin/memory` | Admin: все memory entries |
| `DELETE /api/admin/memory/:id` | Admin: удалить entry |
| `POST /api/admin/memory/clear-sessions` | Admin: очистить сессии |
| `GET /api/analytics` | Аналитика (задачи, стоимость, модели) |
| `GET /api/admin/schedule` | Admin: все scheduled tasks |
| `GET /api/templates` | Список шаблонов задач |
| `GET /api/templates/:id` | Конкретный шаблон |
| `GET /api/connectors` | Интеграции (статус) |
| `POST /api/connectors/:id/connect` | Подключить интеграцию |
| `POST /api/connectors/:id/disconnect` | Отключить |
| `GET /api/files` | Список файлов проектов |
| `POST /api/upload` | Загрузить файл |
| `GET /api/files/:id/download` | Скачать файл |
| `GET /api/files/:id/preview` | Preview файла |
| `GET /api/settings` | Настройки пользователя |
| `PUT /api/settings` | Обновить настройки |
| `GET /api/agents/custom` | Custom agents |
| `POST /api/agents/custom` | Создать агента |
| `DELETE /api/agents/custom/:id` | Удалить агента |

### 6.4 Полный список endpoint coverage

Теперь все 22+ endpoint из `frontend/lib/api.ts` имеют реализацию в бэкенде.

---

## Итоговый счёт изменений

| Категория | Файлы |
|---|---|
| Новые файлы | `core/persistence.py`, `memory_v9/episodic.py`, `memory_v9/continuity.py`, `memory_v9/experimental/README.md`, `CHANGES.md` |
| Изменены | `api/api.py`, `api/compat_all.py`, `core/agent_loop.py`, `shared/memory_v9/engine.py` |
| Исправлены баги | CRIT-A, CRIT-B, CRIT-C, CRIT-E, CRIT-F, CRIT-G, 7 оставшихся проблем |
