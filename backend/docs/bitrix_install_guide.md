# Bitrix Wizard Automation — Технические заметки для ORION

## Что было выяснено в ходе работы

### 1. Правильный архив для установки

Официальный архив для установки на сервер: `start_encode.tar.gz` (~283 MB).

| Редакция | URL |
|---|---|
| Старт | `https://www.1c-bitrix.ru/download/start_encode.tar.gz` |
| Стандарт | `https://www.1c-bitrix.ru/download/standard_encode.tar.gz` |
| Малый бизнес | `https://www.1c-bitrix.ru/download/small_business_encode.tar.gz` |
| Бизнес | `https://www.1c-bitrix.ru/download/business_encode.tar.gz` |

Архив содержит файлы wizard'а установки. После распаковки в корень сайта, `index.php` запускает wizard.

---

### 2. Структура wizard'а

Wizard работает через форму с `iframe` в качестве target (не обычный AJAX). Ответы приходят в формате:

```
[response]window.ajaxForm.SetStatus('51'); window.ajaxForm.Post('b24connector', 'database', 'Текст');[/response]
```

**Шаги wizard'а:**
1. `welcome` → `agreement`
2. `agreement` → `select_database`
3. `select_database` → `requirements`
4. `requirements` → `create_database`
5. `create_database` → `create_modules` ← здесь начинается AJAX-цикл
6. `create_modules` (AJAX-цикл, 39 итераций, 0-100%)
7. При 100%: `__finish` → `create_admin`
8. `create_admin` → `select_wizard`
9. `select_wizard` → `finish`

---

### 3. Ключевые особенности

**Шаг `create_modules` (самый сложный):**
- Wizard не сохраняет состояние между сессиями — каждый раз начинает заново
- Ответ содержит `[response]...[/response]` с JS-кодом
- Из JS нужно извлекать следующий шаг: `window.ajaxForm.Post('step', 'stage', 'desc')`
- При 100% JS содержит: `window.ajaxForm.Post('__finish', '', 'Установка завершена')`

**Шаг `create_database`:**
- Если БД уже содержит таблицы Битрикс → wizard выдаёт ошибку "уже установлен продукт"
- Нужно либо очистить БД, либо пропустить этот шаг

**Шаг `create_admin`:**
- Поля формы: `__wiz_login`, `__wiz_admin_password`, `__wiz_admin_password_confirm`, `__wiz_email`, `__wiz_user_name`, `__wiz_user_surname`
- `NextStepID` на этом шаге = `select_wizard` (не `finish`!)

---

### 4. Формат хэша пароля Битрикс

Битрикс использует SHA-512 crypt:

```php
// Класс: /bitrix/modules/main/lib/security/password.php
$hash = crypt($password, '$6$' . $salt . '$');
// Формат: $6${salt}${hash}
// Длина: ~106 символов
```

---

### 5. Два метода создания admin

#### Метод 1: Через wizard (при первой установке)

```python
data = {
    'CurrentStepID': 'create_admin',
    'NextStepID': 'select_wizard',
    '__wiz_login': 'admin',
    '__wiz_admin_password': 'AdminPass2026!',
    '__wiz_admin_password_confirm': 'AdminPass2026!',
    '__wiz_email': 'admin@example.com',
    '__wiz_user_name': 'Admin',
    '__wiz_user_surname': 'User',
    'StepNext': 'Next',
}
```

#### Метод 2: Напрямую через PHP (надёжнее, работает в любой момент)

```php
<?php
define('B_PROLOG_INCLUDED', true);
$_SERVER['DOCUMENT_ROOT'] = '/var/www/html/bitrix-test';
require_once($_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php');
$user = new CUser;
$ID = $user->Add([
    'LOGIN' => 'admin',
    'PASSWORD' => 'AdminPass2026!',
    'CONFIRM_PASSWORD' => 'AdminPass2026!',
    'EMAIL' => 'admin@example.com',
    'NAME' => 'Admin',
    'ACTIVE' => 'Y',
    'GROUP_ID' => [1],
]);
echo $ID ? "Created: $ID" : "Error: " . $user->LAST_ERROR;
?>
```

---

### 6. Проверка успешной установки

```bash
# Таблиц должно быть ~320+
mysql -u bitrix_user -pPASS bitrix_db -e 'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema="bitrix_db";'

# Проверить admin
mysql -u bitrix_user -pPASS bitrix_db -e 'SELECT ID, LOGIN, EMAIL, ACTIVE FROM b_user;'

# HTTP-ответ панели должен быть 200
curl -s -o /dev/null -w '%{http_code}' http://SERVER_IP/bitrix/admin/
```

---

### 7. Шаблон Битрикс из лендинга

Структура шаблона: `/bitrix/templates/TEMPLATE_NAME/`
- `header.php` — шапка (подключает CSS, JS, навигацию)
- `footer.php` — подвал
- `template_styles.css` — стили шаблона
- `components/` — компоненты шаблона
- `description.php` — описание шаблона

Для редактируемости через админку — использовать компоненты:
- `bitrix:main.include` — включаемые области (редактируемые блоки)
- `bitrix:news.list` — списки новостей/услуг (инфоблоки)
- `bitrix:form.result.new` — формы обратной связи

Активация шаблона через БД:
```sql
UPDATE b_site SET TEMPLATE_ID='dimydiv' WHERE LID='s1';
```

---

### 8. Итоговый результат на тестовом сервере

- **Сервер:** `45.67.57.175`
- **Версия Битрикс:** 1С-Битрикс: Управление сайтом 25.100.500
- **Панель администратора:** http://45.67.57.175/bitrix/admin/
- **Логин:** `admin` / **Пароль:** `AdminPass2026!`
- **БД:** `bitrix_test_db` (320+ таблиц)
