# База знаний Битрикс для ORION v2

## 1. Архитектура шаблона

### Структура папок:
```
/bitrix/templates/[имя_шаблона]/
├── header.php           # Шапка: DOCTYPE, head, навигация
├── footer.php           # Подвал: footer, scripts, </body></html>
├── description.php      # ОБЯЗАТЕЛЬНО: описание шаблона для админки
├── styles.css           # Основные стили (подключается автоматически)
├── template_styles.css  # Дополнительные стили
├── script.js            # Скрипты шаблона
├── images/              # Картинки
├── css/                 # Дополнительные CSS
├── js/                  # Дополнительные JS
└── components/          # Кастомные шаблоны компонентов
    └── bitrix/
        └── news.list/
            └── [имя_шаблона]/
                └── template.php
```

### description.php (ОБЯЗАТЕЛЬНЫЙ файл):
```php
<?php
if(!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED!==true) die();

$arTemplate = [
    "NAME" => "Название шаблона",
    "DESCRIPTION" => "Описание шаблона",
    "SORT" => 100,
    "TYPE" => "MAIN",
];
?>
```

### header.php:
```php
<?php if(!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED!==true) die(); ?>
<!DOCTYPE html>
<html lang="ru">
<head>
<?php $APPLICATION->ShowHead(); ?>
<title><?php $APPLICATION->ShowTitle(); ?></title>
<!-- CSS шаблона подключается автоматически через styles.css -->
<!-- Доп CSS: -->
<link href="<?=SITE_TEMPLATE_PATH?>/css/custom.css" rel="stylesheet">
</head>
<body>
<div id="panel"><?php $APPLICATION->ShowPanel(); ?></div>
```

### footer.php:
```php
<?php if(!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED!==true) die(); ?>
<footer>
    <!-- footer content -->
</footer>
<script src="<?=SITE_TEMPLATE_PATH?>/js/main.js"></script>
</body>
</html>
```

### ПРАВИЛА ПУТЕЙ К РЕСУРСАМ:

В PHP файлах (header.php, footer.php, template.php, include/*.php):
```php
<img src="<?=SITE_TEMPLATE_PATH?>/images/logo.png">
<link href="<?=SITE_TEMPLATE_PATH?>/css/style.css">
<script src="<?=SITE_TEMPLATE_PATH?>/js/main.js"></script>
```

В обычных CSS файлах (styles.css):
```css
/* Относительные пути внутри папки шаблона: */
background: url(images/bg.png);
/* или: */
background: url(../images/bg.png);
/* SITE_TEMPLATE_PATH здесь НЕ работает — это не PHP */
```

В обычных JS файлах (script.js):
```javascript
// Использовать относительные или абсолютные пути
// SITE_TEMPLATE_PATH здесь НЕ работает
```

ИТОГО: SITE_TEMPLATE_PATH — только в PHP файлах.
В CSS/JS — обычные пути.


## 2. Инфоблоки

### 2.1 Определить SITE_ID (НЕ хардкодить s1):
```php
// Узнать реальный SITE_ID:
$rsSites = CSite::GetList($by="sort", $order="desc");
while ($arSite = $rsSites->Fetch()) {
    echo $arSite["LID"] . " - " . $arSite["NAME"] . "\n";
}
// Или через SQL: SELECT LID FROM b_lang
```

### 2.2 Создание типа инфоблока (обязательно LANG):
```php
<?php
require_once($_SERVER["DOCUMENT_ROOT"]."/bitrix/modules/main/include/prolog_before.php");

if (!CModule::IncludeModule("iblock")) {
    die("ERROR: iblock module not installed");
}

// IDEMPOTENT: проверить существует ли тип
$dbType = CIBlockType::GetByID("content");
if ($dbType->Fetch()) {
    echo "Type 'content' already exists\n";
} else {
    $obBlocktype = new CIBlockType;
    $res = $obBlocktype->Add([
        'ID' => 'content',
        'SECTIONS' => 'Y',
        'IN_RSS' => 'N',
        'SORT' => 100,
        'LANG' => [          // ОБЯЗАТЕЛЬНО!
            'ru' => [
                'NAME' => 'Контент сайта',
                'SECTION_NAME' => 'Разделы',
                'ELEMENT_NAME' => 'Элементы'
            ]
        ]
    ]);
    if (!$res) {
        echo "ERROR type: " . $obBlocktype->LAST_ERROR . "\n";
    } else {
        echo "Type 'content' created OK\n";
    }
}
?>
```

### 2.3 Создание инфоблока (обязательно SITE_ID):
```php
// IDEMPOTENT: проверить существует ли инфоблок
$rsIBlock = CIBlock::GetList([], ["CODE" => "services", "TYPE" => "content"]);
if ($arIBlock = $rsIBlock->Fetch()) {
    $iblockId = $arIBlock["ID"];
    echo "IBlock 'services' already exists (ID=$iblockId)\n";
} else {
    // Определить SITE_ID
    $siteId = CSite::GetDefSite(); // или конкретный ID
    
    $ib = new CIBlock;
    $iblockId = $ib->Add([
        'ACTIVE' => 'Y',
        'NAME' => 'Услуги',
        'CODE' => 'services',
        'IBLOCK_TYPE_ID' => 'content',
        'SITE_ID' => [$siteId],  // ОБЯЗАТЕЛЬНО! Реальный ID, не хардкод
        'LIST_PAGE_URL' => '',
        'DETAIL_PAGE_URL' => '',
        'SORT' => 100,
    ]);
    if (!$iblockId) {
        echo "ERROR iblock: " . $ib->LAST_ERROR . "\n";
    } else {
        echo "IBlock 'services' created (ID=$iblockId)\n";
    }
}
```

### 2.4 Создание свойств (IDEMPOTENT):
```php
// Проверить существует ли свойство
$rsProp = CIBlockProperty::GetList([], [
    "IBLOCK_ID" => $iblockId, "CODE" => "PRICE"
]);
if (!$rsProp->Fetch()) {
    $ibp = new CIBlockProperty;
    $ibp->Add([
        'IBLOCK_ID' => $iblockId,
        'NAME' => 'Цена',
        'CODE' => 'PRICE',
        'ACTIVE' => 'Y',
        'SORT' => 100,
        'PROPERTY_TYPE' => 'S',
        // Типы: S=строка, N=число, F=файл, L=список, E=привязка
    ]);
}
```

### 2.5 Добавление элементов:
```php
$el = new CIBlockElement;
$elementId = $el->Add([
    'IBLOCK_ID' => $iblockId,
    'NAME' => 'Мужская стрижка',
    'ACTIVE' => 'Y',
    'PREVIEW_TEXT' => 'Классическая мужская стрижка',
    'SORT' => 100,
    'PROPERTY_VALUES' => [
        'PRICE' => '2500',
    ],
]);
if (!$elementId) {
    echo "ERROR element: " . $el->LAST_ERROR . "\n";
}
```


## 3. Компоненты

### 3.1 bitrix:news.list — для СПИСКОВ (услуги, тарифы, отзывы):
```php
<?php $APPLICATION->IncludeComponent(
    "bitrix:news.list",
    "services_cards",   // имя шаблона компонента
    [
        "IBLOCK_TYPE" => "content",
        "IBLOCK_ID" => $iblockId,  // НЕ хардкодить число!
        "NEWS_COUNT" => "20",
        "SORT_BY1" => "SORT",
        "SORT_ORDER1" => "ASC",
        "FIELD_CODE" => ["NAME", "PREVIEW_TEXT", "PREVIEW_PICTURE"],
        "PROPERTY_CODE" => ["PRICE", "ICON"],
        "CACHE_TYPE" => "A",
        "CACHE_TIME" => "3600",
    ]
); ?>
```

### 3.2 Шаблон компонента (template.php):
Путь: /bitrix/templates/[шаблон]/components/bitrix/news.list/[имя]/template.php

```php
<?php if(!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED!==true) die(); ?>

<?php if(!empty($arResult["ITEMS"])): ?>
<div class="cards-grid">
    <?php foreach($arResult["ITEMS"] as $arItem): ?>
    <div class="card">
        <?php if(!empty($arItem["PREVIEW_PICTURE"]["SRC"])): ?>
        <img src="<?=$arItem["PREVIEW_PICTURE"]["SRC"]?>" 
             alt="<?=htmlspecialchars($arItem["NAME"])?>">
        <?php else: ?>
        <!-- fallback если картинки нет -->
        <div class="card-no-image"></div>
        <?php endif; ?>
        
        <h3><?=htmlspecialchars($arItem["NAME"])?></h3>
        
        <?php if($arItem["PREVIEW_TEXT"]): ?>
        <p><?=$arItem["PREVIEW_TEXT"]?></p>
        <?php endif; ?>
        
        <?php if(!empty($arItem["PROPERTIES"]["PRICE"]["VALUE"])): ?>
        <span class="price"><?=$arItem["PROPERTIES"]["PRICE"]["VALUE"]?> ₽</span>
        <?php endif; ?>
    </div>
    <?php endforeach; ?>
</div>
<?php else: ?>
<p>Нет данных</p>
<?php endif; ?>
```

### 3.3 bitrix:main.include — ТОЛЬКО для уникальных блоков:
```php
<?php $APPLICATION->IncludeComponent(
    "bitrix:main.include", "",
    ["AREA_FILE_SHOW" => "file", "PATH" => "/include/hero.php"]
); ?>
```
Использовать для: hero секция, контакты, footer содержимое.
НЕ использовать для: услуги, тарифы, отзывы, портфолио — там news.list!


## 4. Назначение шаблона сайту

### Проверить текущий шаблон:
```sql
SELECT TEMPLATE FROM b_lang WHERE LID='s1';
```

### Назначить шаблон:
```php
$obSite = new CSite;
$obSite->Update('s1', ['TEMPLATE' => 'dimydiv']);
```

### Или через SQL:
```sql
UPDATE b_lang SET TEMPLATE='dimydiv' WHERE LID='s1';
```

### Также обновить b_site_template:
```sql
INSERT INTO b_site_template (SITE_ID, TEMPLATE, SORT) 
VALUES ('s1', 'dimydiv', 1)
ON DUPLICATE KEY UPDATE TEMPLATE='dimydiv';
```


## 5. Очистка кэша

### ОБЯЗАТЕЛЬНО после любых изменений:
```bash
# Через SSH:
rm -rf /var/www/html/bitrix/cache/*
rm -rf /var/www/html/bitrix/managed_cache/*
rm -rf /var/www/html/bitrix/stack_cache/*
```

### Или через PHP:
```php
<?php
require_once($_SERVER["DOCUMENT_ROOT"]."/bitrix/modules/main/include/prolog_before.php");
BXClearCache(true);
echo "Cache cleared";
?>
```

### Когда чистить:
- После создания/изменения шаблона
- После создания/изменения инфоблоков
- После добавления компонентов
- После изменения данных если используется кэш


## 6. Формы обратной связи

### Через CEvent (email события):
```php
<?php
require_once($_SERVER["DOCUMENT_ROOT"]."/bitrix/modules/main/include/prolog_before.php");

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $name = htmlspecialchars(trim($_POST['name'] ?? ''));
    $phone = htmlspecialchars(trim($_POST['phone'] ?? ''));
    
    if (empty($name) || empty($phone)) {
        die(json_encode(['error' => 'Заполните обязательные поля']));
    }
    
    CEvent::Send("FEEDBACK_FORM", SITE_ID, [
        "AUTHOR" => $name,
        "PHONE" => $phone,
        "EMAIL" => htmlspecialchars($_POST['email'] ?? ''),
    ]);
    
    echo json_encode(['success' => true, 'message' => 'Заявка отправлена']);
}
?>
```


## 7. Проверка после интеграции (ПОЛНЫЙ ЧЕКЛИСТ)

### Template layer:
```bash
# Шаблон существует
ls /var/www/html/bitrix/templates/ШАБЛОН/header.php
ls /var/www/html/bitrix/templates/ШАБЛОН/footer.php
ls /var/www/html/bitrix/templates/ШАБЛОН/description.php

# Шаблон назначен сайту
mysql -u USER -pPASS DB -e "SELECT TEMPLATE FROM b_lang"

# Ассеты без 404
curl -s http://SITE/ | grep -oP 'src="[^"]*"' | while read src; do
  url=$(echo $src | tr -d '"' | sed 's/src=//')
  code=$(curl -sI "http://SITE$url" -o /dev/null -w '%{http_code}')
  [ "$code" != "200" ] && echo "404: $url"
done
```

### CMS layer:
```bash
# Тип инфоблока с языком
mysql -u USER -pPASS DB -e "SELECT * FROM b_iblock_type"
mysql -u USER -pPASS DB -e "SELECT * FROM b_iblock_type_lang"

# Инфоблоки существуют
mysql -u USER -pPASS DB -e "SELECT ID,NAME,CODE,IBLOCK_TYPE_ID FROM b_iblock"

# Элементы есть
mysql -u USER -pPASS DB -e "SELECT COUNT(*) as cnt, IBLOCK_ID FROM b_iblock_element GROUP BY IBLOCK_ID"
```

### Dynamic layer:
```bash
# Компоненты news.list подключены (не только main.include)
grep -r "news.list" /var/www/html/index.php /var/www/html/include/ 2>/dev/null

# КРИТИЧЕСКАЯ ПРОВЕРКА: изменить данные → увидеть на сайте
# 1. Изменить название элемента в инфоблоке
# 2. Очистить кэш
# 3. Открыть сайт
# 4. Убедиться что новое название видно
```

### Admin layer:
```bash
# Админка реально работает (не лендинг)
curl -s http://SITE/bitrix/admin/ | grep -c "authorize\|bx-admin\|bitrix_sessid"
# Должно быть > 0

# Логин работает
curl -s -X POST http://SITE/bitrix/admin/ \
  -d "AUTH_FORM=Y&TYPE=AUTH&USER_LOGIN=admin&USER_PASSWORD=PASS" \
  -c cookies.txt -L | grep -c "bitrix/admin"
```

### Runtime layer:
```bash
# Правильный nginx root
grep -A5 "server_name\|root" /etc/nginx/sites-enabled/* | head -20

# Кэш очищен
ls /var/www/html/bitrix/cache/ 2>/dev/null | wc -l
# Должно быть 0 или минимум
```


## 8. Pipeline интеграции лендинга в Битрикс

Порядок шагов (для ORION агента):

1. ОПРЕДЕЛИТЬ SITE_ID:
   SQL: SELECT LID FROM b_lang

2. ПРОВЕРИТЬ NGINX:
   Правильный root, PHP работает

3. ПОДГОТОВИТЬ ШАБЛОН:
   Создать папку, header.php, footer.php, description.php
   Перенести CSS/JS/images
   Заменить пути в PHP на SITE_TEMPLATE_PATH

4. НАЗНАЧИТЬ ШАБЛОН сайту:
   UPDATE b_lang SET TEMPLATE='имя'

5. СОЗДАТЬ ТИП ИНФОБЛОКА (с проверкой существования):
   CIBlockType->Add() с LANG

6. СОЗДАТЬ ИНФОБЛОКИ (с проверкой существования):
   CIBlock->Add() с SITE_ID

7. СОЗДАТЬ СВОЙСТВА (с проверкой существования):
   CIBlockProperty->Add()

8. НАПОЛНИТЬ ДАННЫМИ:
   CIBlockElement->Add()

9. ЗАМЕНИТЬ СТАТИКУ НА КОМПОНЕНТЫ:
   Списки → bitrix:news.list
   Уникальные блоки → bitrix:main.include

10. ОЧИСТИТЬ КЭШ:
    rm -rf bitrix/cache/* bitrix/managed_cache/*

11. ПРОВЕРИТЬ АДМИНКУ:
    Логин, навигация по инфоблокам

12. ПРОВЕРИТЬ ДИНАМИКУ:
    Изменить элемент в админке → увидеть на сайте

13. VERIFIER + JUDGE


## 9. Частые ошибки (anti-patterns)

1. Тип инфоблока без LANG → "Неверный тип блока" в админке
2. Инфоблок без SITE_ID → не привязан к сайту
3. Относительные пути в PHP шаблонах → картинки 404
4. Списки через main.include → данные в админке не влияют на сайт
5. PHP скрипты через CLI → CMain not found (только HTTP)
6. Шаблон создан но не назначен → сайт на старом шаблоне
7. Компонент с неверным IBLOCK_ID → пустой список
8. Свойства не созданы → данные без нужных полей
9. Кэш не очищен → старое состояние на сайте
10. Админка отдаёт лендинг → установка не завершена
11. Дубликаты при повторном запуске → проверять существование перед созданием
12. Нет description.php → шаблон не виден в админке
13. Нет проверки "изменил в админке → видно на сайте" → интеграция не завершена
---

## 10. Шаблоны компонентов — обязательные файлы

### A. description.php обязателен

Каждый кастомный шаблон компонента ДОЛЖЕН содержать `description.php`, иначе шаблон не будет виден в визуальном редакторе Bitrix.

```php
<?php if(!defined("B_PROLOG_INCLUDED")||B_PROLOG_INCLUDED!==true)die();
$arTemplateDescription = [
    'NAME'        => 'Название шаблона',
    'DESCRIPTION' => 'Описание шаблона',
    'PREVIEW'     => '',
];
```

### B. Назначение шаблона сайту

После создания папки шаблона необходимо убедиться что он назначен:

```sql
SELECT TEMPLATE FROM b_lang;
-- Должно быть имя папки шаблона, например: dentapro
```

Назначить через API:
```php
CSite::Update('s1', ['TEMPLATE' => [['TEMPLATE' => 'dentapro', 'CONDITION' => '', 'SORT' => 100]]]);
```

### C. Готовые template.php для services/reviews/doctors/portfolio

**services_cards** (`bitrix/templates/{TEMPLATE}/components/bitrix/news.list/services_cards/template.php`):
```php
<?php if(!defined("B_PROLOG_INCLUDED")||B_PROLOG_INCLUDED!==true)die(); ?>
<?php foreach($arResult["ITEMS"] as $arItem): ?>
<article class="rounded-[28px] border border-slate-100 bg-white p-6 shadow-xl">
    <h3 class="text-lg font-extrabold text-slate-900"><?= htmlspecialchars($arItem["NAME"]) ?></h3>
    <?php if($arItem["PREVIEW_TEXT"]): ?>
    <p class="mt-2 text-sm text-slate-600"><?= $arItem["PREVIEW_TEXT"] ?></p>
    <?php endif; ?>
    <?php if($arItem["PROPERTIES"]["PRICE"]["VALUE"]): ?>
    <p class="mt-3 font-bold text-sky-700">от <?= $arItem["PROPERTIES"]["PRICE"]["VALUE"] ?> ₽</p>
    <?php endif; ?>
</article>
<?php endforeach; ?>
```

**reviews_cards** (`bitrix/templates/{TEMPLATE}/components/bitrix/news.list/reviews_cards/template.php`):
```php
<?php if(!defined("B_PROLOG_INCLUDED")||B_PROLOG_INCLUDED!==true)die(); ?>
<?php foreach($arResult["ITEMS"] as $arItem): ?>
<article class="rounded-[28px] border border-slate-100 bg-white p-6 shadow-xl">
    <p class="text-sm text-slate-600"><?= $arItem["PREVIEW_TEXT"] ?></p>
    <div class="mt-4 font-bold text-slate-900"><?= htmlspecialchars($arItem["NAME"]) ?></div>
    <?php if($arItem["PROPERTIES"]["CITY"]["VALUE"]): ?>
    <div class="text-xs text-slate-400"><?= htmlspecialchars($arItem["PROPERTIES"]["CITY"]["VALUE"]) ?></div>
    <?php endif; ?>
</article>
<?php endforeach; ?>
```

### D. Обязательная проверка: admin → frontend cycle

После создания шаблонов и заполнения инфоблоков ВСЕГДА выполнять:

1. Зайти в Bitrix Admin → Контент → нужный инфоблок
2. Изменить название элемента (добавить тестовую метку, например "ТЕСТ17")
3. Сохранить
4. Очистить кэш: `rm -rf bitrix/cache/* bitrix/managed_cache/*`
5. Открыть сайт и проверить: `curl -s http://SITE/ | grep -c "ТЕСТ17"` — должно быть >= 1
6. Если 0 — интеграция НЕ завершена

---

## 11. SQL — только как аварийный repair

Основной путь работы с Битрикс — через API:
- `CSite::Update()` для назначения шаблона
- `CIBlock::GetList()` для поиска инфоблоков по CODE
- `CIBlockElement::Update()` для обновления данных элементов
- `BXClearCache(true)` для очистки кэша

Прямой SQL (`UPDATE b_lang`, `UPDATE b_iblock_element`) использовать ТОЛЬКО как аварийный repair если API недоступен.

---

## 12. Настройка PHP для Битрикс (idempotent override)

НЕ делать `echo >> php.ini`. Создавать override-файл:

```bash
PHP_VER=$(php -v | head -1 | grep -oP '\d+\.\d+')
cat > /etc/php/${PHP_VER}/fpm/conf.d/99-orion-bitrix.ini << 'INI'
max_input_vars = 10000
mbstring.func_overload = 0
opcache.revalidate_freq = 0
INI
systemctl restart php${PHP_VER}-fpm
```

Проверять через web (не CLI):
```bash
echo '<?php echo ini_get("max_input_vars");' > ${BITRIX_ROOT}/check_ini.php
curl -s http://SITE/check_ini.php   # должно быть 10000
rm ${BITRIX_ROOT}/check_ini.php
```

---

## 13. Архитектурное правило: инфоблоки vs include

| Тип контента | Правильный подход |
|---|---|
| Услуги, врачи, отзывы, тарифы, портфолио | `bitrix:news.list` с инфоблоком |
| Hero-секция, контакты, форма (уникальные) | `bitrix:main.include` |
| Навигация, футер | Шаблон сайта (header.php / footer.php) |

**Нельзя**: хардкодить списки в PHP include-файлах — тогда редактирование через админку не работает.

---
## 14. КРИТИЧНО: Установка Битрикс — НЕ использовать browser_click

**ЗАПРЕЩЕНО** использовать `browser_click` для прохождения веб-установщика Битрикс (`bitrixsetup.php`).
Playwright зависает на элементах `#agree_license_id` и других кнопках установщика.

**ПРАВИЛЬНЫЙ ПУТЬ** — использовать `bitrix_installer.py` или `bitrix_wizard_operator.py`:
```python
from bitrix_installer import BitrixInstaller
installer = BitrixInstaller(ssh_executor=ssh_fn)
result = installer.install(
    server={"host": "45.67.57.175", "username": "root", "password": "..."},
    install_path="/var/www/html",
    db_config={"db_name": "bitrix_db", "db_user": "bitrix_user", "db_password": "..."}
)
```

Или через SSH + curl (если Python модуль недоступен):
```bash
# Шаг 1: Скачать установщик
cd /var/www/html && wget -q https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php

# Шаг 2: Пройти установщик через curl (НЕ через браузер)
# Установщик Битрикс поддерживает POST-запросы для каждого шага
curl -s -X POST http://45.67.57.175/bitrixsetup.php \
  -d "step=1&agree_license=Y&edition=start" > /tmp/step1.html

# Шаг 3: Проверить что ядро установлено
ls /var/www/html/bitrix/modules/ | wc -l  # должно быть > 10
curl -sI http://45.67.57.175/bitrix/admin/ | head -1  # должно быть HTTP 200 или 302
```

**ПРИЗНАК УСПЕШНОЙ УСТАНОВКИ:**
- `curl -sI http://SITE/bitrix/admin/` → HTTP 302 (редирект на /bitrix/admin/index.php)
- `ls /var/www/html/bitrix/admin/` → содержит `index.php`
- `cat /var/www/html/bitrix/.settings.php` → содержит `connections`

---
## 15. КРИТИЧНО: Стандартный режим — защита от потери SSE

В режиме **Стандарт** (не PRO/Turbo) агент НЕ имеет background thread.
При потере SSE-соединения задача **умирает**.

**Правила для длинных операций:**
1. Разбивать установку на короткие SSH-команды (не более 30 секунд каждая)
2. НЕ использовать `cp -a` для больших директорий — использовать `rsync` с прогрессом
3. Скачивание архивов через `wget -q --show-progress` с таймаутом
4. После каждой операции делать `curl -sI http://SITE/` для проверки

**Пример правильной установки через SSH (без browser):**
```bash
# Быстрая установка Битрикс через готовый архив
cd /var/www/html
wget -q -O bitrix.tar.gz "https://www.1c-bitrix.ru/download/start_encode.tar.gz" --timeout=120
tar -xzf bitrix.tar.gz --strip-components=1
chown -R www-data:www-data /var/www/html
chmod -R 755 /var/www/html
```

---
## 16. КРИТИЧНО: Проверка готовности Битрикс к работе

После установки ВСЕГДА проверять:
```bash
# 1. Ядро установлено
[ -f /var/www/html/bitrix/admin/index.php ] && echo "OK" || echo "FAIL: no admin"

# 2. Настройки БД
[ -f /var/www/html/bitrix/.settings.php ] && echo "OK" || echo "FAIL: no settings"

# 3. HTTP ответ
curl -sI http://45.67.57.175/ | head -1  # HTTP 200 или 302

# 4. Админка доступна
curl -sI http://45.67.57.175/bitrix/admin/ | head -1  # HTTP 302 (редирект на login)

# 5. PHP работает
curl -s http://45.67.57.175/ | grep -c "bitrix" || echo "WARN: no bitrix in HTML"
```

Если любая проверка FAIL — останавливаться и исправлять ПЕРЕД созданием шаблона.

---
## 17. Правильная структура файлов Битрикс-шаблона

Шаблон ДОЛЖЕН находиться в:
```
/var/www/html/local/templates/TEMPLATE_NAME/
├── .description.php          # ОБЯЗАТЕЛЬНО: описание шаблона
├── header.php                # Шапка сайта
├── footer.php                # Подвал сайта
├── template_styles.css       # CSS стили
├── script.js                 # JavaScript
└── components/               # Шаблоны компонентов
    └── bitrix/
        └── news.list/
            ├── services_cards/
            │   ├── template.php      # ОБЯЗАТЕЛЬНО
            │   └── .description.php  # ОБЯЗАТЕЛЬНО
            ├── reviews_cards/
            │   ├── template.php
            │   └── .description.php
            └── doctors_cards/
                ├── template.php
                └── .description.php
```

**ОБЯЗАТЕЛЬНЫЕ поля в .description.php:**
```php
<?php
$TEMPLATE_NAME = "Название шаблона";
$TEMPLATE_DESCRIPTION = "Описание";
$TEMPLATE_SUPPORT_MULTI_SITE = "Y";
$TEMPLATE_SUPPORT_MULTI_LANG = "Y";
```

**Назначение шаблона сайту через API (НЕ через SQL):**
```php
// В PHP-скрипте через Bitrix API:
require_once $_SERVER["DOCUMENT_ROOT"]."/bitrix/modules/main/include/prolog_before.php";
CSite::Update("s1", ["TEMPLATE" => [["TEMPLATE" => "TEMPLATE_NAME", "CONDITION" => ""]]]);
BXClearCache(true);
```


## Раздел 18: Установка Битрикс — wizard через HTTP, НЕ через браузер

**КРИТИЧНО:** НИКОГДА не использовать `browser_click` / `browser_navigate` для установщика Битрикс.
Wizard работает через iframe + POST-запросы. Playwright зависает на кнопках wizard (особенно `#agree_license_id`).

### СПОСОБ 1 — HTTP POST wizard (предпочтительный)

Шаги wizard через curl/requests:

```
1. GET /bitrixsetup.php          → скачивание архива Битрикс
2. POST CurrentStepID=welcome    → agreement (принятие лицензии)
3. POST CurrentStepID=agreement  → select_database
4. POST CurrentStepID=select_database → requirements
5. POST CurrentStepID=requirements    → create_database (с данными БД)
6. POST CurrentStepID=create_database → create_modules (AJAX цикл, ~39 итераций)
7. При 100%: POST CurrentStepID=__finish → create_admin
8. POST CurrentStepID=create_admin (с логином/паролем)
9. POST CurrentStepID=select_wizard → finish
```

Ответы в формате: `[response]window.ajaxForm.Post(...)...[/response]`

Пример curl-запроса для шага agreement:
```bash
curl -s -X POST "http://HOST/bitrix/wizard/index.php" \
  -d "CurrentStepID=agreement&NEXT_STEP=select_database&agree_license=Y" \
  -H "Content-Type: application/x-www-form-urlencoded"
```

Пример curl для create_database:
```bash
curl -s -X POST "http://HOST/bitrix/wizard/index.php" \
  -d "CurrentStepID=create_database&NEXT_STEP=create_modules&DB_HOST=localhost&DB_NAME=bitrix_db&DB_LOGIN=bitrix&DB_PASSWORD=bitrix123&DB_ROOT_LOGIN=root&DB_ROOT_PASSWORD=&INSTALL_DB=Y" \
  -H "Content-Type: application/x-www-form-urlencoded"
```

### СПОСОБ 2 — скачать архив напрямую + CLI (быстрее)

```bash
# Скачать архив
wget https://www.1c-bitrix.ru/download/start_encode.tar.gz -O /tmp/bitrix.tar.gz
# Распаковать в web root
tar -xzf /tmp/bitrix.tar.gz -C /var/www/html/

# Создать dbconn.php
cat > /var/www/html/bitrix/php_interface/dbconn.php << 'EOF'
<?php
define("DBHost", "localhost");
define("DBLogin", "bitrix");
define("DBPassword", "bitrix123");
define("DBName", "bitrix_db");
define("DBPersistent", false);
define("DBDebug", false);
define("DBDebugToFile", false);
define("DELAY_DB_CONNECT", true);
define("CHARSET", "UTF-8");
EOF

# Создать .settings.php
cat > /var/www/html/bitrix/.settings.php << 'EOF'
<?php
return array(
  'connections' => array(
    'value' => array(
      'default' => array(
        'className' => '\\Bitrix\\Main\\DB\\MysqliConnection',
        'host' => 'localhost',
        'database' => 'bitrix_db',
        'login' => 'bitrix',
        'password' => 'bitrix123',
        'options' => 2,
      ),
    ),
    'readonly' => false,
  ),
  'utf_mode' => array('value' => true, 'readonly' => true),
  'cache_flags' => array('value' => array('config_options' => 3600, 'site_template' => 3600)),
  'cookies' => array('value' => array('secure' => false, 'httpOnly' => true)),
  'exception_handling' => array('value' => array('debug' => false, 'handled_errors_types' => E_ALL & ~E_NOTICE & ~E_STRICT & ~E_DEPRECATED, 'exception_errors_types' => E_ERROR | E_PARSE | E_COMPILE_ERROR | E_COMPILE_WARNING, 'ignore_silence' => false, 'assertion_throws_exception' => true, 'assertion_error_type' => 256, 'log' => null)),
);
EOF

# Создать admin через PHP API
php -r "
define('STOP_STATISTICS', true);
define('NO_AGENT_STATISTIC', 'Y');
define('NO_AGENT_CHECK', true);
define('DisableEventsCheck', true);
\$_SERVER['DOCUMENT_ROOT'] = '/var/www/html';
require('/var/www/html/bitrix/modules/main/include/prolog_before.php');
\$user = new CUser;
\$arFields = array(
    'NAME' => 'Admin',
    'EMAIL' => 'admin@dentapro.ru',
    'LOGIN' => 'admin',
    'PASSWORD' => 'Admin123!',
    'CONFIRM_PASSWORD' => 'Admin123!',
    'GROUP_ID' => array(1),
    'ACTIVE' => 'Y',
);
\$id = \$user->Add(\$arFields);
echo \$id ? 'Admin created: '.\$id : 'Error: '.\$user->LAST_ERROR;
"
```

### Проверка успешной установки

```bash
# Проверить что .settings.php создан
test -f /var/www/html/bitrix/.settings.php && echo "OK" || echo "FAIL"

# Проверить что admin панель доступна
curl -sI http://HOST/bitrix/admin/ | grep "HTTP/1.1 200\|HTTP/1.1 302"

# Проверить max_input_vars
php -r "echo ini_get('max_input_vars');" # должно быть >= 10000
```

### ПРАВИЛО: Порядок действий при установке Битрикс

1. Скачать архив через `wget` (НЕ через browser)
2. Распаковать `tar -xzf`
3. Создать БД через `mysql -e "CREATE DATABASE..."`
4. Создать `dbconn.php` и `.settings.php` вручную
5. Настроить права: `chown -R www-data:www-data /var/www/html/`
6. Настроить nginx/apache VirtualHost
7. Создать admin через PHP CLI (НЕ через browser wizard)
8. Настроить `max_input_vars = 10000` в php.ini
9. Очистить кэш: `rm -rf /var/www/html/bitrix/cache/*`
10. Проверить: `curl -sI http://HOST/bitrix/admin/` → 200 или 302

**ЗАПРЕЩЕНО:** browser_click, browser_navigate, browser_fill_form для любых шагов установки Битрикс.
