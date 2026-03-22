# BEGET CONTROL PANEL — ИНСТРУКЦИЯ ДЛЯ БРАУЗЕРНОГО АГЕНТА

> Этот файл — точная инструкция для автоматизации действий в панели управления Beget.
> Все селекторы верифицированы вручную 19.03.2026.
> Beget использует Vue.js (Vuetify) + Nuxt.js + TailwindCSS.
> **Ключевой принцип:** Beget использует атрибут `st=""` как семантический идентификатор элементов.
> Используй `[st="..."]` CSS-селекторы — они стабильнее чем id или class.

---

## 1. ВХОД В ПАНЕЛЬ

### URL
```
https://cp.beget.com/login
```

### Поля формы входа

| Поле | CSS-селектор | XPath | Тип |
|------|-------------|-------|-----|
| Логин | `#login` | `//input[@id="login"]` | `input[type="text"]` |
| Пароль | `#password` | `//input[@id="password"]` | `input[type="password"]` |
| Кнопка входа | `button[type="submit"]` | `//button[@type="submit"]` | `button` |

### Алгоритм входа (пошагово)
```
1. Открыть URL: https://cp.beget.com/login
2. Найти поле логина: document.querySelector('#login')
3. Очистить и ввести логин: element.value = 'asmksm58'
4. Найти поле пароля: document.querySelector('#password')
5. Очистить и ввести пароль: element.value = '9DVTHeKiYuZD'
6. Нажать кнопку: document.querySelector('button[type="submit"]').click()
7. Дождаться редиректа на: https://cp.beget.com/main
8. Проверить успех: document.querySelector('[st="customer-balance"]') должен быть виден
```

### Проверка успешного входа
- URL после входа: `https://cp.beget.com/main`
- Элемент на странице: `[st="customer-balance"]` — показывает баланс
- Элемент: `[st="button-main-multiaccounts"]` — показывает логин пользователя

---

## 2. ГЛАВНАЯ СТРАНИЦА ПАНЕЛИ

### URL
```
https://cp.beget.com/main
```

### Навигационное меню (левая панель)

| Раздел | URL | Описание |
|--------|-----|----------|
| Web hosting | `https://cp.beget.com/main` | Главная страница |
| Domains | `https://cp.beget.com/domains` | Управление доменами |
| **DNS** | `https://cp.beget.com/dns` | **DNS записи** |
| Mail | `https://cp.beget.com/mail` | Почта |
| Sites | `https://cp.beget.com/site` | Сайты |
| File Manager | `https://cp.beget.com/files` | Файловый менеджер |

### Карточки на главной странице (CSS-селекторы)

```javascript
// Прямые ссылки на разделы
document.querySelector('a[href="/dns"]')          // DNS
document.querySelector('a[href="/domains"]')       // Домены
document.querySelector('a[href="/site"]')          // Сайты
document.querySelector('a[href="/files"]')         // Файлы
```

---

## 3. РАЗДЕЛ DNS

### URL
```
https://cp.beget.com/dns
```

### Структура страницы DNS

Страница содержит:
1. **Выбор домена** — dropdown для выбора домена
2. **Форма "Add fast"** — быстрое добавление записи
3. **Список "Subzones and DNS records"** — все записи домена

### Выбор домена

```javascript
// Контейнер выбора домена
[st="dns-select-domain-input-container"]  // DIV (combobox)

// Поле ввода для поиска домена
[st="dns-select-domain-input"]  // INPUT

// Как выбрать домен:
// 1. Кликнуть на [st="dns-select-domain-input-container"]
// 2. Ввести имя домена в [st="dns-select-domain-input"]
// 3. Выбрать из выпадающего списка нужный домен
```

### Форма быстрого добавления записи ("Add fast")

```javascript
// Контейнер формы
[st="fast-add-form"]  // FORM

// Поле "Name" (имя записи / субдомен)
[st="dns-fast-add-name"]        // INPUT, id="input-23"
// Пример: ввести "" для корневой записи, "www" для www-субдомена

// Поле "Type" (тип записи: A, MX, CNAME, TXT, SRV)
[st="dns-fast-add-type"]        // DIV[role="combobox"]
// Внутренний input: id="input-26"
// Доступные типы: MX, SRV, TXT (для технического домена)
// Для обычных доменов: A, AAAA, CNAME, MX, TXT, SRV, CAA, NS

// Поле "Value" / "IP" (значение записи)
// Зависит от типа записи:
[st="input-dns-exchange-field"]   // INPUT, id="input-31" — для MX (Exchange)
[st="input-dns-preference-field"] // INPUT, id="input-29" — для MX (Preference/Priority)
// Для A-записи: поле Value появляется после выбора типа A

// Кнопка "Add new" (сохранить)
[st="button-dns-fast-add"]      // BUTTON[type="submit"], текст: "Add new"
```

### Как добавить A-запись (пошагово)

```
1. Перейти на: https://cp.beget.com/dns
2. Выбрать домен в [st="dns-select-domain-input-container"]
3. В форме "Add fast":
   a. Поле Name ([st="dns-fast-add-name"]): ввести субдомен или оставить пустым
   b. Поле Type ([st="dns-fast-add-type"]): кликнуть и выбрать "A"
   c. Появится поле Value/IP: ввести IP-адрес
4. Нажать [st="button-dns-fast-add"] (кнопка "Add new")
5. Дождаться обновления списка записей
```

### Управление существующими записями

```javascript
// Список всех записей
[st="dns-record-list"]          // Контейнер списка

// Строка с записью
[st="record-row"]               // Строка записи

// Тип записи в строке (например "A", "MX")
.tw-text-text-primary.tw-min-w-12   // DIV с типом

// Значение записи
[st="dns-record-data"]          // DIV со значением (IP или hostname)

// Кнопки действий (появляются при наведении на строку)
[st="button-dns-edit-node"]     // BUTTON — редактировать запись
[st="button-dns-delete-node"]   // BUTTON — удалить запись
[st="button-dns-discard-node"]  // BUTTON — отменить изменения
[st="button-dns-add-node"]      // BUTTON — добавить запись в группу
```

### Как изменить A-запись существующего домена

```
1. Перейти на: https://cp.beget.com/dns
2. Выбрать домен
3. В разделе "Subzones and DNS records" найти нужный домен
4. Кликнуть на строку домена чтобы раскрыть список записей
5. Найти строку с типом "A"
6. Навести мышь на строку — появятся кнопки
7. Нажать [st="button-dns-edit-node"] (карандаш) для редактирования
8. Изменить значение IP
9. Нажать кнопку сохранения (галочка)
```

---

## 4. РАЗДЕЛ САЙТЫ (Sites)

### URL
```
https://cp.beget.com/site
```

### Управление сайтами

```javascript
// Список сайтов
[st="sites-list"]

// Кнопка добавить сайт
[st="button-add-site"]

// Поле имени сайта
[st="input-site-name"]
```

---

## 5. ФАЙЛОВЫЙ МЕНЕДЖЕР

### URL
```
https://cp.beget.com/files
```

---

## 6. ВАЖНЫЕ ОСОБЕННОСТИ BEGET

### Vue.js Combobox (выпадающие списки)
Beget использует Vuetify combobox. Для взаимодействия:

```javascript
// Открыть dropdown
document.querySelector('[st="dns-fast-add-type"]').click()

// Дождаться появления listbox
const listbox = document.querySelector('[role="listbox"]')

// Выбрать опцию по тексту
const options = listbox.querySelectorAll('.v-list-item')
const targetOption = Array.from(options).find(o => o.textContent.trim() === 'A')
targetOption.click()
```

### Динамические ID полей
ID полей (`input-23`, `input-26` и т.д.) могут меняться при перезагрузке страницы.
**Всегда используй `[st="..."]` атрибуты вместо `#input-XX`**.

### Атрибут `st` — главный идентификатор
Beget специально добавил атрибут `st` для автоматизации и тестирования.
Это стабильный идентификатор, который не меняется при обновлениях.

```javascript
// Правильно (стабильно):
document.querySelector('[st="dns-fast-add-name"]')

// Неправильно (нестабильно):
document.querySelector('#input-23')
document.querySelector('.v-field__input')
```

### Список DNS Beget серверов
```
ns1.beget.com
ns2.beget.com
ns1.beget.pro
ns2.beget.pro
```

---

## 7. АЛГОРИТМ: ДОБАВИТЬ A-ЗАПИСЬ ДЛЯ ДОМЕНА

```python
# Псевдокод для ORION браузерного агента

def add_a_record(domain: str, subdomain: str, ip: str):
    # Шаг 1: Войти
    navigate("https://cp.beget.com/login")
    fill("#login", "asmksm58")
    fill("#password", "9DVTHeKiYuZD")
    click("button[type='submit']")
    wait_for_url("https://cp.beget.com/main")
    
    # Шаг 2: Перейти в DNS
    navigate("https://cp.beget.com/dns")
    
    # Шаг 3: Выбрать домен
    click('[st="dns-select-domain-input-container"]')
    fill('[st="dns-select-domain-input"]', domain)
    click(f'[role="option"]:contains("{domain}")')
    
    # Шаг 4: Заполнить форму
    fill('[st="dns-fast-add-name"]', subdomain)  # "" для корневой
    
    # Выбрать тип A
    click('[st="dns-fast-add-type"]')
    wait_for('[role="listbox"]')
    click('.v-list-item:contains("A")')
    
    # Ввести IP
    fill('[st="input-dns-value-field"]', ip)  # поле появляется после выбора типа A
    
    # Шаг 5: Сохранить
    click('[st="button-dns-fast-add"]')
    wait_for_success_message()
```

---

## 8. БРАУЗЕРНЫЕ ИНСТРУМЕНТЫ ORION

При использовании браузерных инструментов ORION:

### Навигация
```
browser_navigate(url="https://cp.beget.com/dns", intent="navigational")
```

### Ввод текста
```
# Найти индекс элемента через browser_view()
# Использовать browser_input(index=N, text="значение", press_enter=False)
```

### Клик
```
# Найти индекс через browser_view()
# browser_click(index=N)
```

### JavaScript для сложных действий
```
# browser_console_exec(javascript="document.querySelector('[st=...']').click()")
```

### Поиск элемента по тексту
```
browser_find_keyword(keyword="Add new")
```

---

## 9. ТИПИЧНЫЕ ОШИБКИ И РЕШЕНИЯ

| Ошибка | Причина | Решение |
|--------|---------|---------|
| Форма не отправляется | Vuetify validation | Проверить все обязательные поля |
| Dropdown не открывается | Нужен клик именно на стрелку | Кликнуть на `[role="combobox"]` или стрелку `i[hint="$vuetify.open"]` |
| A-запись недоступна | Технический домен `.beget.tech` | Использовать собственный домен |
| Сессия истекла | Timeout | Повторить вход через `https://cp.beget.com/login` |
| Кнопки редактирования не видны | Нужен hover | Навести мышь на строку записи |

---

## 10. ПОЛНАЯ КАРТА ЭЛЕМЕНТОВ DNS СТРАНИЦЫ

```
https://cp.beget.com/dns
│
├── [st="dns-select-domain-input-container"]  ← Выбор домена (combobox)
│   └── [st="dns-select-domain-input"]        ← Поле ввода домена
│
├── [st="button-dns-edit-ns-servers"]         ← Ссылка "Edit DNS Servers"
├── [st="button-dns-show-plain-zone"]         ← Ссылка "Zone text"
│
├── [st="fast-add-form"]                      ← Форма "Add fast"
│   ├── [st="dns-fast-add-name"]              ← Поле "Name" (INPUT)
│   ├── [st="dns-fast-add-type"]              ← Поле "Type" (combobox)
│   │   └── [st="dns-fast-add-type"] input   ← id="input-26"
│   ├── [st="input-dns-preference-field"]     ← Поле "Preference" (для MX)
│   ├── [st="input-dns-exchange-field"]       ← Поле "Exchange" (для MX)
│   └── [st="button-dns-fast-add"]            ← Кнопка "Add new" (submit)
│
└── [st="dns-record-list"]                    ← Список записей
    └── [st="record-row"]                     ← Строка записи
        ├── .tw-text-text-primary.tw-min-w-12 ← Тип (A/MX/TXT)
        ├── [st="dns-record-data"]            ← Значение записи
        ├── [st="button-dns-edit-node"]       ← Кнопка редактирования
        ├── [st="button-dns-delete-node"]     ← Кнопка удаления
        └── [st="button-dns-add-node"]        ← Кнопка добавления
```

---

*Файл создан: 19.03.2026*
*Верифицировано: Manus браузерный агент*
*Аккаунт: asmksm58 (Beget)*
