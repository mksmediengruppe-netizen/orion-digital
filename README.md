# ORION Digital - AI Agent Platform

ORION — это автономная платформа на базе ИИ, способная выполнять сложные задачи: от написания кода до полного деплоя сайтов на удалённые серверы через SSH.

## 🚀 Архитектура

Платформа состоит из двух основных компонентов:

1. **Frontend (Vanilla JS + HTML/CSS)**
   - Адаптивный интерфейс в стиле ChatGPT
   - Поддержка Markdown, подсветки синтаксиса (Prism.js)
   - Рендеринг артефактов (HTML/CSS/JS) прямо в браузере через iframe
   - Устойчивая система кэширования чатов (защита от потери данных при рестартах API)

2. **Backend (Python + Flask + Gunicorn)**
   - **AgentLoop (`agent_loop.py`)**: Ядро автономного агента. Поддерживает вызов инструментов (Tool Calling), работу с памятью, SSH-подключения и деплой.
   - **Orchestrator (`orchestrator_v2.py`)**: Планировщик задач. Разбивает сложные запросы на фазы и управляет их выполнением.
   - **App (`app.py`)**: REST API для фронтенда, управление сессиями, биллинг и маршрутизация запросов.

## 🛠️ Последние критические исправления (Аудит)

В ходе последнего аудита были выявлены и устранены следующие критические баги, которые мешали агенту выполнять сложные задачи (например, деплой сайта "Северный ветер"):

### 1. Зависание LLM Stream (AgentLoop)
- **Проблема:** Агент зависал навсегда при чтении ответов от OpenRouter API, если соединение закрывалось некорректно (CLOSE-WAIT).
- **Решение:** Внедрён `threading.Timer` (180 сек) для принудительного закрытия `resp.close()` и обработки таймаутов в `_call_ai_stream`.

### 2. Ошибки контекста Flask (App)
- **Проблема:** `RuntimeError: Working outside of request context` при сохранении стоимости запроса в фоновом потоке генерации.
- **Решение:** Идентификатор пользователя (`request.user_id`) теперь сохраняется в локальную переменную до запуска генератора.

### 3. Отсутствующие функции подсчёта стоимости (App)
- **Проблема:** `NameError: name '_now_iso' is not defined` и `_calc_cost` при завершении задач в Pro-режиме.
- **Решение:** Добавлены глобальные хелперы `_now_iso()` и `_calc_cost()` для корректного биллинга.

### 4. Блокировка SSH-задач (AgentLoop)
- **Проблема:** Запросы со словом "визитка" ошибочно триггерили `ArtifactGenerator` (генерацию картинок) вместо полноценного AgentLoop с SSH.
- **Решение:** Обновлена логика `_check_force_tool` — запросы, содержащие SSH-доступы или команды деплоя, теперь всегда направляются в AgentLoop.

### 5. Исчезновение чатов на фронтенде (Frontend)
- **Проблема:** При протухании токена (401 Unauthorized) или рестарте бэкенда список чатов очищался.
- **Решение:** Внедрено агрессивное кэширование в `localStorage`. Чаты сохраняются перед любым API-запросом и мгновенно восстанавливаются при ошибках или перелогине.

### 6. Ошибка парсинга фаз (Orchestrator)
- **Проблема:** `IndexError: list index out of range`, когда LLM возвращала пустой массив фаз.
- **Решение:** Добавлена проверка `if phases:` перед доступом к `phases[0]`.

## 🌐 Инфраструктура

- **Сервер:** Ubuntu 22.04
- **Веб-сервер:** Nginx (Reverse Proxy) + Gunicorn
- **База данных:** SQLite (`database.sqlite`) / JSON fallback
- **LLM Провайдер:** OpenRouter (DeepSeek, Claude, OpenAI)

## 🔒 Безопасность
- Пароли и API-ключи хранятся в `.env`
- SSH-доступы, передаваемые пользователем, используются только в рамках текущей сессии агента и не сохраняются в открытом виде.


## Deployment

### Requirements
- Python 3.12+
- Docker (for Qdrant vector DB)
- Node.js 22+ (for frontend build, optional)

### Quick Start
```bash
cd /var/www/orion/backend
cp .env.example .env
# Fill in OPENROUTER_API_KEY and ORION_ENCRYPT_KEY
gunicorn --worker-class gthread --workers 3 --threads 4 --bind 0.0.0.0:3510 --timeout 1800 wsgi:app
```

### Models
| Mode | Orchestrator | Developer | Judge | Cost Limit |
|------|-------------|-----------|-------|------------|
| Fast | GPT-5.4 Mini | GPT-5.4 Mini | GPT-5.4 Mini | $2 |
| Standard | GPT-5.4 | GPT-5.4 Mini | Claude Sonnet 4.6 | $5 |
| Premium | GPT-5.4 | GPT-5.4 | Claude Sonnet 4.6 | $15 |

Emergency fallback: Claude Opus 4 (only in FALLBACK_CHAINS)

### Architecture
- Backend: Flask + Gunicorn (3 workers, 4 threads)
- Frontend: Vanilla JS SPA
- Database: SQLite (main) + Qdrant (vector memory)
- Auth: HttpOnly cookie (SameSite=Lax)
