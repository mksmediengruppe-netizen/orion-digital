# ORION Knowledge Base: Битрикс24 API & Приложения
# ===================================================
# Загрузить в /var/www/orion/backend/data/knowledge_base/bitrix24_api.md

---

## ОСНОВЫ БИТРИКС24 API

### Два способа подключения

**1. Вебхуки (простой, без приложения)**
```
https://your-domain.bitrix24.ru/rest/1/abc123xyz/crm.lead.add.json
```
Создать: Битрикс24 → Настройки → Интеграции → Вебхуки → Добавить входящий вебхук
Выбрать права: CRM, Задачи, и т.д.

**2. OAuth-приложение (для публикации на маркетплейсе)**
```
https://your-domain.bitrix24.ru/rest/crm.lead.add.json?auth=ACCESS_TOKEN
```
Регистрация: dev.1c-bitrix.ru → Добавить приложение

### Формат вызова REST API

```python
import requests

BITRIX_WEBHOOK = "https://company.bitrix24.ru/rest/1/your_webhook_key/"

# Создать лид
response = requests.post(f"{BITRIX_WEBHOOK}crm.lead.add.json", json={
    "fields": {
        "TITLE": "Заявка с сайта",
        "NAME": "Иван",
        "LAST_NAME": "Петров",
        "PHONE": [{"VALUE": "+79001234567", "VALUE_TYPE": "WORK"}],
        "EMAIL": [{"VALUE": "ivan@mail.ru", "VALUE_TYPE": "WORK"}],
        "SOURCE_ID": "WEB",
        "COMMENTS": "Заявка с лендинга кофейни",
    }
})
lead_id = response.json().get("result")
```

---

## CRM: ЛИДЫ, СДЕЛКИ, КОНТАКТЫ

### Лиды (crm.lead.*)

```python
# Создать лид
crm.lead.add(fields={"TITLE": "Новый лид", "NAME": "Иван", "PHONE": [{"VALUE": "+7900..."}]})

# Получить лид
crm.lead.get(id=123)

# Список лидов с фильтром
crm.lead.list(filter={"STATUS_ID": "NEW", ">DATE_CREATE": "2024-01-01"}, select=["ID", "TITLE", "NAME"], order={"ID": "DESC"})

# Обновить лид
crm.lead.update(id=123, fields={"STATUS_ID": "IN_PROCESS", "COMMENTS": "Перезвонить"})

# Удалить лид
crm.lead.delete(id=123)
```

### Сделки (crm.deal.*)

```python
# Создать сделку
crm.deal.add(fields={
    "TITLE": "Продажа сайта",
    "STAGE_ID": "NEW",          # Стадия воронки
    "CATEGORY_ID": 0,           # Воронка (0 = основная)
    "OPPORTUNITY": 150000,       # Сумма
    "CURRENCY_ID": "RUB",
    "CONTACT_ID": 456,          # Привязка к контакту
    "COMPANY_ID": 789,          # Привязка к компании
    "ASSIGNED_BY_ID": 1,        # Ответственный
    "SOURCE_ID": "WEB",
    "UF_CRM_123456": "значение" # Пользовательское поле
})

# Стадии воронки по умолчанию:
# NEW, PREPARATION, PREPAYMENT_INVOICE, EXECUTING, FINAL_INVOICE, WON, LOSE

# Список сделок
crm.deal.list(filter={"STAGE_ID": "NEW", "ASSIGNED_BY_ID": 1}, select=["ID", "TITLE", "OPPORTUNITY"])

# Двигать по воронке
crm.deal.update(id=100, fields={"STAGE_ID": "EXECUTING"})
```

### Контакты (crm.contact.*)

```python
crm.contact.add(fields={
    "NAME": "Иван",
    "LAST_NAME": "Петров",
    "PHONE": [{"VALUE": "+79001234567", "VALUE_TYPE": "WORK"}],
    "EMAIL": [{"VALUE": "ivan@mail.ru", "VALUE_TYPE": "WORK"}],
    "COMPANY_ID": 789,
})
```

### Компании (crm.company.*)

```python
crm.company.add(fields={
    "TITLE": "ООО Ромашка",
    "PHONE": [{"VALUE": "+74951234567"}],
    "WEB": [{"VALUE": "https://romashka.ru"}],
    "INDUSTRY": "IT",
})
```

---

## ЗАДАЧИ (tasks.task.*)

```python
# Создать задачу
tasks.task.add(fields={
    "TITLE": "Подготовить КП",
    "DESCRIPTION": "Коммерческое предложение для клиента",
    "RESPONSIBLE_ID": 1,
    "CREATED_BY": 1,
    "DEADLINE": "2024-12-31T18:00:00",
    "PRIORITY": 2,  # 0=низкий, 1=средний, 2=высокий
    "GROUP_ID": 5,  # ID группы/проекта
    "TAGS": ["КП", "Продажи"],
    "UF_CRM_TASK": ["D_100"],  # Привязка к сделке 100
})

# Список задач
tasks.task.list(filter={"RESPONSIBLE_ID": 1, "STATUS": 2}, select=["ID", "TITLE", "DEADLINE"])

# Статусы задач:
# 1=новая, 2=в работе, 3=ждёт контроля, 4=условно завершена, 5=завершена, 6=отложена
```

---

## БИЗНЕС-ПРОЦЕССЫ (bizproc.*)

```python
# Запустить бизнес-процесс
bizproc.workflow.start(
    TEMPLATE_ID=15,
    DOCUMENT_ID=["crm", "CCrmDocumentDeal", "DEAL_100"],
    PARAMETERS={"Parameter1": "value1"}
)

# Список шаблонов БП
bizproc.workflow.template.list(filter={"MODULE_ID": "crm", "ENTITY": "CCrmDocumentDeal"})
```

---

## РАЗРАБОТКА ПРИЛОЖЕНИЙ Б24

### Структура приложения

```
my-b24-app/
├── index.php          # Главная страница (встраивается в iframe Б24)
├── install.php        # Установка приложения
├── handler.php        # Обработчик событий
├── settings.php       # Настройки
├── js/
│   └── app.js
├── css/
│   └── style.css
└── vendor/
    └── bitrix24-php-sdk/
```

### index.php (главная страница приложения)

```php
<?php
require_once 'vendor/autoload.php';

// Подключить JS SDK Битрикс24
?>
<!DOCTYPE html>
<html>
<head>
    <script src="//api.bitrix24.com/api/v1/"></script>
    <script src="//api.bitrix24.com/api/v1/pull/"></script>
</head>
<body>
<div id="app">Загрузка...</div>

<script>
BX24.init(function() {
    // Приложение инициализировано
    
    // Получить текущего пользователя
    BX24.callMethod('user.current', {}, function(result) {
        console.log('User:', result.data());
    });
    
    // Вызвать REST API
    BX24.callMethod('crm.lead.list', {
        filter: {"STATUS_ID": "NEW"},
        select: ["ID", "TITLE", "NAME"]
    }, function(result) {
        if (result.error()) {
            console.error(result.error());
        } else {
            var leads = result.data();
            // Отобразить лиды
        }
    });
    
    // Batch-запрос (несколько вызовов за раз)
    BX24.callBatch({
        leads: ['crm.lead.list', {filter: {"STATUS_ID": "NEW"}}],
        deals: ['crm.deal.list', {filter: {"STAGE_ID": "NEW"}}],
        contacts: ['crm.contact.list', {filter: {">ID": 0}}]
    }, function(result) {
        var leads = result.leads.data();
        var deals = result.deals.data();
        var contacts = result.contacts.data();
    });
});

// Изменить размер iframe
BX24.resizeWindow(800, 600);

// Открыть слайдер
BX24.openApplication({width: 800}, function() {
    // Слайдер открыт
});
</script>
</body>
</html>
```

### install.php (установка)

```php
<?php
require_once 'vendor/autoload.php';

$result = $_REQUEST;

if ($result['event'] == 'ONAPPINSTALL') {
    // Сохранить токены
    $authData = [
        'access_token' => $result['auth']['access_token'],
        'refresh_token' => $result['auth']['refresh_token'],
        'domain' => $result['auth']['domain'],
        'member_id' => $result['auth']['member_id'],
    ];
    file_put_contents('auth.json', json_encode($authData));
    
    // Зарегистрировать обработчики событий
    $webhook = "https://your-server.com/handler.php";
    
    // При создании лида
    BX24\Event::bind('ONCRMLEADADD', $webhook);
    // При изменении сделки
    BX24\Event::bind('ONCRMDEALUPDATE', $webhook);
}
?>
<script src="//api.bitrix24.com/api/v1/"></script>
<script>BX24.installFinish();</script>
```

### handler.php (обработка событий)

```php
<?php
$event = $_REQUEST['event'];
$data = $_REQUEST['data'];

switch ($event) {
    case 'ONCRMLEADADD':
        $leadId = $data['FIELDS']['ID'];
        // Новый лид создан — обработать
        // Например: отправить уведомление в Telegram
        break;
        
    case 'ONCRMDEALUPDATE':
        $dealId = $data['FIELDS']['ID'];
        // Сделка обновлена
        break;
}

http_response_code(200);
echo json_encode(['status' => 'ok']);
```

### Python SDK

```python
# pip install bitrix24-rest
from bitrix24 import Bitrix24

bx24 = Bitrix24("https://company.bitrix24.ru/rest/1/webhook_key/")

# Создать лид
result = bx24.callMethod("crm.lead.add", fields={
    "TITLE": "Заявка с сайта",
    "NAME": "Иван",
    "PHONE": [{"VALUE": "+79001234567"}],
})

# Batch
results = bx24.callBatch({
    "leads": ("crm.lead.list", {"filter": {"STATUS_ID": "NEW"}}),
    "deals": ("crm.deal.list", {"filter": {"STAGE_ID": "NEW"}}),
})
```

---

## ВЕБХУКИ (входящие и исходящие)

### Входящий вебхук (Б24 → ваш сервер)

Битрикс24 → Настройки → Интеграции → Вебхуки → Входящий
URL: `https://your-server.com/b24webhook.php`
Событие: ONCRMLEADADD

```php
// b24webhook.php
$data = json_decode(file_get_contents('php://input'), true);
if (!$data) $data = $_REQUEST;

$event = $data['event'] ?? '';
$leadId = $data['data']['FIELDS']['ID'] ?? '';

// Обработка
file_put_contents('webhook_log.txt', date('Y-m-d H:i:s') . " Event: $event, Lead: $leadId\n", FILE_APPEND);
```

### Исходящий вебхук (ваш сервер → Б24)

```python
# При отправке формы на сайте → создать лид в Б24
import requests

def create_lead_from_form(name, phone, email, message):
    webhook_url = "https://company.bitrix24.ru/rest/1/key/"
    
    response = requests.post(f"{webhook_url}crm.lead.add.json", json={
        "fields": {
            "TITLE": f"Заявка: {name}",
            "NAME": name,
            "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
            "EMAIL": [{"VALUE": email, "VALUE_TYPE": "WORK"}],
            "COMMENTS": message,
            "SOURCE_ID": "WEB",
            "UTM_SOURCE": "website",
        }
    })
    
    return response.json().get("result")
```

---

## ПОЛЬЗОВАТЕЛЬСКИЕ ПОЛЯ

```python
# Создать пользовательское поле для сделки
crm.deal.userfield.add(fields={
    "FIELD_NAME": "DELIVERY_DATE",
    "USER_TYPE_ID": "date",
    "EDIT_FORM_LABEL": {"ru": "Дата доставки", "en": "Delivery Date"},
    "LIST_COLUMN_LABEL": {"ru": "Доставка"},
    "MANDATORY": "Y",
})

# Типы полей:
# string, integer, double, boolean, date, datetime, 
# enumeration (список), file, url, address, money,
# crm_status, crm, iblock_element, employee
```

---

## СМАРТ-ПРОЦЕССЫ (CRM 2.0)

```python
# Создать элемент смарт-процесса
crm.item.add(entityTypeId=128, fields={
    "title": "Проект: Сайт для клиента",
    "stageId": "DT128_1:NEW",
    "assignedById": 1,
    "ufCrm1_1234567890": "значение кастомного поля",
})

# Список элементов
crm.item.list(entityTypeId=128, filter={"assignedById": 1}, select=["id", "title", "stageId"])
```

---

## ЧАСТЫЕ ЗАДАЧИ

### Интеграция формы сайта с Б24 (полный пример)

```python
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)
B24_WEBHOOK = "https://company.bitrix24.ru/rest/1/key/"

@app.route('/api/feedback', methods=['POST'])
def feedback():
    data = request.json
    
    # 1. Создать контакт
    contact = requests.post(f"{B24_WEBHOOK}crm.contact.add.json", json={
        "fields": {
            "NAME": data.get("name", ""),
            "PHONE": [{"VALUE": data.get("phone", ""), "VALUE_TYPE": "WORK"}],
            "EMAIL": [{"VALUE": data.get("email", ""), "VALUE_TYPE": "WORK"}],
        }
    }).json()
    contact_id = contact.get("result")
    
    # 2. Создать сделку
    deal = requests.post(f"{B24_WEBHOOK}crm.deal.add.json", json={
        "fields": {
            "TITLE": f"Заявка: {data.get('name', 'Аноним')}",
            "CONTACT_ID": contact_id,
            "STAGE_ID": "NEW",
            "SOURCE_ID": "WEB",
            "COMMENTS": data.get("message", ""),
        }
    }).json()
    
    return jsonify({"success": True, "deal_id": deal.get("result")})
```

### Telegram-уведомление при новом лиде

```python
import requests

TELEGRAM_BOT_TOKEN = "123456:ABC..."
TELEGRAM_CHAT_ID = "-100123456789"

def notify_new_lead(lead_data):
    text = f"🔔 Новый лид!\n\nИмя: {lead_data['NAME']}\nТелефон: {lead_data['PHONE']}\nИсточник: {lead_data['SOURCE_ID']}"
    
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    })
```
