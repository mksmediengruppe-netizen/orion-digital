# ORION Knowledge Base: n8n Workflow Automation
# ================================================
# Загрузить в /var/www/orion/backend/data/knowledge_base/n8n_workflows.md

---

## ОСНОВЫ n8n

### Установка

```bash
# Docker (рекомендуется)
docker run -d --name n8n -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  -e N8N_BASIC_AUTH_ACTIVE=true \
  -e N8N_BASIC_AUTH_USER=admin \
  -e N8N_BASIC_AUTH_PASSWORD=password \
  -e WEBHOOK_URL=https://n8n.yourdomain.ru/ \
  n8nio/n8n

# С PostgreSQL (production)
docker run -d --name n8n -p 5678:5678 \
  -e DB_TYPE=postgresdb \
  -e DB_POSTGRESDB_DATABASE=n8n \
  -e DB_POSTGRESDB_HOST=postgres \
  -e DB_POSTGRESDB_USER=n8n \
  -e DB_POSTGRESDB_PASSWORD=secret \
  -e N8N_ENCRYPTION_KEY=your-encryption-key \
  -e WEBHOOK_URL=https://n8n.yourdomain.ru/ \
  n8nio/n8n
```

### n8n API

```python
import requests

N8N_URL = "https://n8n.yourdomain.ru"
N8N_API_KEY = "n8n_api_key_here"

headers = {"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"}

# Список workflow
workflows = requests.get(f"{N8N_URL}/api/v1/workflows", headers=headers).json()

# Создать workflow
new_wf = requests.post(f"{N8N_URL}/api/v1/workflows", headers=headers, json={
    "name": "Обработка лидов",
    "nodes": [...],
    "connections": {...},
    "active": False
}).json()

# Активировать
requests.patch(f"{N8N_URL}/api/v1/workflows/{wf_id}", headers=headers, json={"active": True})

# Выполнить вручную
requests.post(f"{N8N_URL}/api/v1/workflows/{wf_id}/run", headers=headers, json={
    "data": {"key": "value"}
})
```

---

## ТИПОВЫЕ WORKFLOW

### 1. Форма на сайте → Б24 лид → Telegram уведомление

```json
{
  "name": "Сайт → Битрикс24 → Telegram",
  "nodes": [
    {
      "name": "Webhook",
      "type": "n8n-nodes-base.webhook",
      "position": [250, 300],
      "parameters": {
        "httpMethod": "POST",
        "path": "new-lead",
        "responseMode": "responseNode"
      }
    },
    {
      "name": "Создать лид в Б24",
      "type": "n8n-nodes-base.httpRequest",
      "position": [450, 300],
      "parameters": {
        "method": "POST",
        "url": "https://company.bitrix24.ru/rest/1/key/crm.lead.add.json",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "fields[TITLE]", "value": "={{$json.name}} — заявка с сайта"},
            {"name": "fields[NAME]", "value": "={{$json.name}}"},
            {"name": "fields[PHONE][0][VALUE]", "value": "={{$json.phone}}"},
            {"name": "fields[EMAIL][0][VALUE]", "value": "={{$json.email}}"},
            {"name": "fields[COMMENTS]", "value": "={{$json.message}}"},
            {"name": "fields[SOURCE_ID]", "value": "WEB"}
          ]
        }
      }
    },
    {
      "name": "Telegram уведомление",
      "type": "n8n-nodes-base.telegram",
      "position": [650, 300],
      "parameters": {
        "operation": "sendMessage",
        "chatId": "-100123456789",
        "text": "🔔 Новая заявка!\n\nИмя: {{$node['Webhook'].json.name}}\nТелефон: {{$node['Webhook'].json.phone}}\nEmail: {{$node['Webhook'].json.email}}"
      }
    },
    {
      "name": "Ответ клиенту",
      "type": "n8n-nodes-base.respondToWebhook",
      "position": [850, 300],
      "parameters": {
        "respondWith": "json",
        "responseBody": "{\"success\": true}"
      }
    }
  ],
  "connections": {
    "Webhook": {"main": [[{"node": "Создать лид в Б24", "type": "main", "index": 0}]]},
    "Создать лид в Б24": {"main": [[{"node": "Telegram уведомление", "type": "main", "index": 0}]]},
    "Telegram уведомление": {"main": [[{"node": "Ответ клиенту", "type": "main", "index": 0}]]}
  }
}
```

### 2. Новая сделка в Б24 → Создать задачу → Email менеджеру

```json
{
  "name": "Б24 сделка → Задача + Email",
  "nodes": [
    {
      "name": "Триггер Б24",
      "type": "n8n-nodes-base.webhook",
      "parameters": {
        "httpMethod": "POST",
        "path": "b24-deal-created"
      }
    },
    {
      "name": "Получить детали сделки",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "https://company.bitrix24.ru/rest/1/key/crm.deal.get.json",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [{"name": "id", "value": "={{$json.data.FIELDS.ID}}"}]
        }
      }
    },
    {
      "name": "Создать задачу",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "https://company.bitrix24.ru/rest/1/key/tasks.task.add.json",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "fields[TITLE]", "value": "Обработать сделку: ={{$json.result.TITLE}}"},
            {"name": "fields[RESPONSIBLE_ID]", "value": "={{$json.result.ASSIGNED_BY_ID}}"},
            {"name": "fields[DEADLINE]", "value": "={{$now.plus(3, 'days').toISO()}}"},
            {"name": "fields[DESCRIPTION]", "value": "Сумма: ={{$json.result.OPPORTUNITY}} руб."},
            {"name": "fields[UF_CRM_TASK][0]", "value": "D_={{$json.result.ID}}"},
            {"name": "fields[PRIORITY]", "value": "2"}
          ]
        }
      }
    },
    {
      "name": "Email менеджеру",
      "type": "n8n-nodes-base.emailSend",
      "parameters": {
        "fromEmail": "crm@company.ru",
        "toEmail": "manager@company.ru",
        "subject": "Новая сделка: ={{$node['Получить детали сделки'].json.result.TITLE}}",
        "text": "Создана новая сделка на сумму ={{$node['Получить детали сделки'].json.result.OPPORTUNITY}} руб."
      }
    }
  ]
}
```

### 3. Ежедневный отчёт по CRM

```json
{
  "name": "Ежедневный CRM отчёт",
  "nodes": [
    {
      "name": "Cron",
      "type": "n8n-nodes-base.cron",
      "parameters": {
        "triggerTimes": {"item": [{"hour": 9, "minute": 0}]}
      }
    },
    {
      "name": "Новые лиды за вчера",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "https://company.bitrix24.ru/rest/1/key/crm.lead.list.json",
        "method": "POST",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "filter[>DATE_CREATE]", "value": "={{$now.minus(1, 'days').format('YYYY-MM-DD')}}"},
            {"name": "select[0]", "value": "ID"},
            {"name": "select[1]", "value": "TITLE"}
          ]
        }
      }
    },
    {
      "name": "Выигранные сделки",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "https://company.bitrix24.ru/rest/1/key/crm.deal.list.json",
        "method": "POST",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "filter[STAGE_ID]", "value": "WON"},
            {"name": "filter[>CLOSEDATE]", "value": "={{$now.minus(1, 'days').format('YYYY-MM-DD')}}"}
          ]
        }
      }
    },
    {
      "name": "Формирование отчёта",
      "type": "n8n-nodes-base.code",
      "parameters": {
        "jsCode": "const leads = $input.first().json;\nconst deals = $input.last().json;\nreturn [{json: {report: `Отчёт за ${new Date().toLocaleDateString()}:\\n\\nНовых лидов: ${leads.total}\\nВыигранных сделок: ${deals.total}`}}];"
      }
    },
    {
      "name": "Отправить в Telegram",
      "type": "n8n-nodes-base.telegram",
      "parameters": {
        "operation": "sendMessage",
        "chatId": "-100123456789",
        "text": "={{$json.report}}"
      }
    }
  ]
}
```

### 4. Речевая аналитика (звонки → транскрипция → анализ)

```json
{
  "name": "Речевая аналитика звонков",
  "nodes": [
    {
      "name": "Webhook (новый звонок завершён)",
      "type": "n8n-nodes-base.webhook",
      "parameters": {"path": "call-completed", "httpMethod": "POST"}
    },
    {
      "name": "Скачать запись звонка",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "={{$json.recording_url}}",
        "responseFormat": "file"
      }
    },
    {
      "name": "Транскрипция (OpenAI Whisper)",
      "type": "n8n-nodes-base.openAi",
      "parameters": {
        "operation": "transcribe",
        "modelId": "whisper-1",
        "binaryPropertyName": "data"
      }
    },
    {
      "name": "Анализ разговора (GPT)",
      "type": "n8n-nodes-base.openAi",
      "parameters": {
        "operation": "message",
        "modelId": "gpt-4",
        "messages": {
          "values": [{
            "content": "Проанализируй разговор менеджера с клиентом. Оцени:\n1. Вежливость (1-10)\n2. Выявление потребностей (1-10)\n3. Работа с возражениями (1-10)\n4. Итог разговора\n5. Рекомендации\n\nТранскрипция:\n={{$json.text}}"
          }]
        }
      }
    },
    {
      "name": "Сохранить в Б24 (комментарий к сделке)",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "https://company.bitrix24.ru/rest/1/key/crm.timeline.comment.add.json",
        "method": "POST",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "fields[ENTITY_ID]", "value": "={{$node['Webhook'].json.deal_id}}"},
            {"name": "fields[ENTITY_TYPE]", "value": "deal"},
            {"name": "fields[COMMENT]", "value": "🎙 Анализ звонка:\\n={{$json.choices[0].message.content}}"}
          ]
        }
      }
    }
  ]
}
```

### 5. Автоматический follow-up

```json
{
  "name": "Auto Follow-up (3 дня без активности)",
  "nodes": [
    {
      "name": "Каждый день в 10:00",
      "type": "n8n-nodes-base.cron",
      "parameters": {"triggerTimes": {"item": [{"hour": 10}]}}
    },
    {
      "name": "Сделки без активности 3+ дней",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "https://company.bitrix24.ru/rest/1/key/crm.deal.list.json",
        "method": "POST",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "filter[STAGE_ID]", "value": "PREPARATION"},
            {"name": "filter[<DATE_MODIFY]", "value": "={{$now.minus(3, 'days').format('YYYY-MM-DD')}}"},
            {"name": "select[0]", "value": "ID"},
            {"name": "select[1]", "value": "TITLE"},
            {"name": "select[2]", "value": "CONTACT_ID"},
            {"name": "select[3]", "value": "ASSIGNED_BY_ID"}
          ]
        }
      }
    },
    {
      "name": "Для каждой сделки",
      "type": "n8n-nodes-base.splitInBatches",
      "parameters": {"batchSize": 1}
    },
    {
      "name": "Создать задачу follow-up",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "url": "https://company.bitrix24.ru/rest/1/key/tasks.task.add.json",
        "method": "POST",
        "sendBody": true,
        "bodyParameters": {
          "parameters": [
            {"name": "fields[TITLE]", "value": "Follow-up: ={{$json.TITLE}}"},
            {"name": "fields[RESPONSIBLE_ID]", "value": "={{$json.ASSIGNED_BY_ID}}"},
            {"name": "fields[DEADLINE]", "value": "={{$now.plus(1, 'days').toISO()}}"},
            {"name": "fields[PRIORITY]", "value": "2"},
            {"name": "fields[UF_CRM_TASK][0]", "value": "D_={{$json.ID}}"}
          ]
        }
      }
    }
  ]
}
```

---

## ПОЛЕЗНЫЕ НОДЫ n8n

| Нода | Для чего |
|------|----------|
| Webhook | Принять HTTP запрос |
| Cron | Расписание (каждый день, час, и т.д.) |
| HTTP Request | Вызвать любой API |
| Code (JS) | Кастомная логика на JavaScript |
| IF | Условие (ветвление) |
| Switch | Множественное ветвление |
| Merge | Объединить данные из нескольких веток |
| Split In Batches | Обработать массив по одному |
| Set | Установить/изменить поля |
| Telegram | Отправить сообщение в Telegram |
| Email Send | Отправить email |
| Google Sheets | Читать/писать таблицы |
| OpenAI | GPT, Whisper, DALL-E |
| Postgres / MySQL | Работа с БД |
| FTP / SFTP | Загрузка файлов |
| Slack | Уведомления в Slack |
| Wait | Пауза (ждать N минут/часов) |

---

## ИНТЕГРАЦИЯ n8n С ORION

ORION может:
1. Создавать workflow через n8n API
2. Активировать/деактивировать workflow
3. Мониторить выполнение
4. Обновлять ноды в существующих workflow

Для этого нужны: n8n API URL и API Key (запросить у пользователя через ask_user).
