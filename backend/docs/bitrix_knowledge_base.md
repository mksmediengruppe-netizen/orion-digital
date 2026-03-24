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
