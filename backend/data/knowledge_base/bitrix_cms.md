# ORION Knowledge Base: 1С-Битрикс CMS
# ========================================
# Загрузить в /var/www/orion/backend/data/knowledge_base/bitrix_cms.md
# Агент будет искать здесь перед web_search

---

## АРХИТЕКТУРА БИТРИКС

### Структура файлов
```
/home/bitrix/www/
├── bitrix/
│   ├── components/        # Стандартные компоненты
│   │   └── bitrix/        # Компоненты ядра
│   ├── templates/         # Шаблоны сайта
│   │   └── .default/      # Шаблон по умолчанию
│   │       ├── header.php
│   │       ├── footer.php
│   │       ├── template_styles.css
│   │       └── components/  # Кастомные шаблоны компонентов
│   ├── modules/           # Модули системы
│   ├── php_interface/     # Обработчики событий
│   │   └── init.php       # Автозагрузка
│   └── admin/             # Админка
├── local/                 # КАСТОМНЫЙ КОД (главная папка для разработки)
│   ├── components/        # Кастомные компоненты
│   ├── templates/         # Кастомные шаблоны сайта
│   ├── modules/           # Кастомные модули
│   ├── php_interface/
│   │   └── init.php       # Кастомная автозагрузка
│   └── classes/           # PSR-4 классы
├── upload/                # Загруженные файлы
└── index.php              # Точка входа
```

ПРАВИЛО: Весь кастомный код в /local/, НЕ в /bitrix/

### Инфоблоки (самое важное)

Инфоблок = таблица данных. Каталог товаров, новости, сотрудники — всё инфоблоки.

Создание инфоблока через API:
```php
use Bitrix\Iblock\IblockTable;

// Создать инфоблок
$result = IblockTable::add([
    'NAME' => 'Новости',
    'CODE' => 'news',
    'IBLOCK_TYPE_ID' => 'content',
    'SITE_ID' => ['s1'],
    'SORT' => 500,
    'GROUP_ID' => ['2' => 'R'],  // Доступ для всех на чтение
]);

// Добавить свойство
use Bitrix\Iblock\PropertyTable;
PropertyTable::add([
    'IBLOCK_ID' => $iblockId,
    'NAME' => 'Автор',
    'CODE' => 'AUTHOR',
    'PROPERTY_TYPE' => 'S',  // S=строка, N=число, L=список, F=файл, E=привязка к элементу
    'MULTIPLE' => 'N',
    'IS_REQUIRED' => 'Y',
]);
```

Типы свойств:
- S — строка
- N — число
- L — список (выпадающий)
- F — файл
- E — привязка к элементу другого инфоблока
- G — привязка к разделу
- HTML — HTML/текст
- S:HTML — HTML редактор
- S:DateTime — дата и время
- S:Map — Яндекс.Карта

### Выборка элементов (D7 API — новый способ)

```php
use Bitrix\Iblock\Elements\ElementNewsTable;  // Автогенерируемый класс

$elements = ElementNewsTable::getList([
    'select' => ['ID', 'NAME', 'PREVIEW_TEXT', 'PREVIEW_PICTURE', 'AUTHOR_VALUE' => 'AUTHOR.VALUE'],
    'filter' => [
        'ACTIVE' => 'Y',
        '>=DATE_ACTIVE_FROM' => new \Bitrix\Main\Type\DateTime(),
    ],
    'order' => ['DATE_ACTIVE_FROM' => 'DESC'],
    'limit' => 10,
]);

while ($element = $elements->fetch()) {
    echo $element['NAME'];
}
```

### Выборка элементов (старый способ — CIBlockElement)

```php
$arFilter = [
    'IBLOCK_ID' => $iblockId,
    'ACTIVE' => 'Y',
    '>=DATE_ACTIVE_FROM' => date('d.m.Y'),
];
$arSelect = ['ID', 'NAME', 'PREVIEW_TEXT', 'PREVIEW_PICTURE', 'PROPERTY_AUTHOR'];

$rsElements = CIBlockElement::GetList(
    ['DATE_ACTIVE_FROM' => 'DESC'],
    $arFilter,
    false,
    ['nPageSize' => 10],
    $arSelect
);

while ($arElement = $rsElements->GetNextElement()) {
    $fields = $arElement->GetFields();
    $props = $arElement->GetProperties();
    echo $fields['NAME'] . ' — ' . $props['AUTHOR']['VALUE'];
}
```

### Компоненты

Вызов компонента на странице:
```php
<?$APPLICATION->IncludeComponent(
    "bitrix:news.list",
    "custom_template",  // Шаблон компонента
    [
        "IBLOCK_TYPE" => "content",
        "IBLOCK_ID" => 5,
        "NEWS_COUNT" => 10,
        "SORT_BY1" => "ACTIVE_FROM",
        "SORT_ORDER1" => "DESC",
        "FILTER_NAME" => "arrFilter",
        "INCLUDE_SUBSECTIONS" => "Y",
        "CACHE_TYPE" => "A",
        "CACHE_TIME" => 3600,
    ]
);?>
```

Кастомный шаблон компонента:
```
/local/templates/main/components/bitrix/news.list/custom_template/
├── template.php      # HTML шаблон
├── style.css         # Стили
├── script.js         # JavaScript
├── result_modifier.php  # Модификация данных перед выводом
└── .parameters.php   # Параметры шаблона
```

template.php:
```php
<?if(!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED!==true) die();?>

<div class="news-list">
<?foreach($arResult["ITEMS"] as $arItem):?>
    <div class="news-item">
        <?if($arItem["PREVIEW_PICTURE"]):?>
            <img src="<?=$arItem["PREVIEW_PICTURE"]["SRC"]?>" alt="<?=$arItem["NAME"]?>">
        <?endif;?>
        <h3><a href="<?=$arItem["DETAIL_PAGE_URL"]?>"><?=$arItem["NAME"]?></a></h3>
        <span class="date"><?=$arItem["DISPLAY_ACTIVE_FROM"]?></span>
        <p><?=$arItem["PREVIEW_TEXT"]?></p>
    </div>
<?endforeach;?>
</div>

<?=$arResult["NAV_STRING"]?>  <!-- Пагинация -->
```

### Многоязычность

```php
// В init.php
AddEventHandler("main", "OnBeforeProlog", function() {
    $lang = $_GET['lang'] ?? 'ru';
    if (in_array($lang, ['ru', 'en', 'cn'])) {
        define('LANGUAGE_ID', $lang);
        define('LANG', $lang);
    }
});

// В шаблоне — переключатель языков
<a href="?lang=ru" <?=LANGUAGE_ID=='ru'?'class="active"':''?>>RU</a>
<a href="?lang=en" <?=LANGUAGE_ID=='en'?'class="active"':''?>>EN</a>
<a href="?lang=cn" <?=LANGUAGE_ID=='cn'?'class="active"':''?>>CN</a>

// Языковые файлы
// /local/templates/main/lang/ru/header.php
$MESS['SITE_TITLE'] = 'Сетевой университет ШОС';
// /local/templates/main/lang/en/header.php
$MESS['SITE_TITLE'] = 'SCO Network University';

// В шаблоне
echo GetMessage('SITE_TITLE');
```

### Формы (веб-формы)

```php
// Создание формы через API
$formId = CForm::Set([
    'NAME' => 'Обратная связь',
    'SID' => 'FEEDBACK',
    'STAT_EVENT' => 'Y',
]);

// Поля формы
CFormField::Set([
    'FORM_ID' => $formId,
    'SID' => 'FIO',
    'TITLE' => 'ФИО',
    'REQUIRED' => 'Y',
    'FIELD_TYPE' => 'text',
]);

// Вывод формы на сайте
$APPLICATION->IncludeComponent("bitrix:form.result.new", "custom", [
    "WEB_FORM_ID" => $formId,
    "SEF_MODE" => "Y",
]);
```

### URL маршрутизация (urlrewrite.php)

```php
// /urlrewrite.php
$arUrlRewrite = [
    ['CONDITION' => '#^/news/#', 'RULE' => '', 'ID' => 'bitrix:news', 'PATH' => '/news/index.php'],
    ['CONDITION' => '#^/programs/#', 'RULE' => '', 'ID' => 'bitrix:news', 'PATH' => '/programs/index.php'],
    ['CONDITION' => '#^/events/#', 'RULE' => '', 'ID' => 'bitrix:news', 'PATH' => '/events/index.php'],
];
```

### Кэширование

```php
// В компоненте
if ($this->startResultCache(3600)) {
    // Тяжёлый код — выполняется раз в час
    $this->endResultCache();
}

// Очистка кэша
BXClearCache(true, '/bitrix/news.list/');
```

### CSV Импорт в инфоблоки

```php
use Bitrix\Main\Loader;
Loader::includeModule('iblock');

$file = fopen('import.csv', 'r');
$header = fgetcsv($file, 0, ';');

while ($row = fgetcsv($file, 0, ';')) {
    $data = array_combine($header, $row);
    
    $el = new CIBlockElement;
    $arFields = [
        'IBLOCK_ID' => 5,
        'NAME' => $data['name'],
        'PREVIEW_TEXT' => $data['description'],
        'ACTIVE' => 'Y',
        'PROPERTY_VALUES' => [
            'AUTHOR' => $data['author'],
            'CATEGORY' => $data['category'],
        ],
    ];
    
    $elementId = $el->Add($arFields);
    if (!$elementId) {
        echo "Error: " . $el->LAST_ERROR;
    }
}
```

### Агенты Битрикс (cron-задачи)

```php
// Регистрация агента
CAgent::AddAgent(
    "MyModule::cleanOldNews();",  // Функция
    "main",
    "N",      // Не периодический (Y — периодический)
    86400,    // Интервал: 24 часа
    "",
    "Y",      // Активен
    ConvertTimeStamp(time() + 3600, "FULL")  // Первый запуск через час
);

// Функция агента
class MyModule {
    public static function cleanOldNews() {
        // Логика очистки
        return "MyModule::cleanOldNews();";  // Вернуть себя для повторного запуска
    }
}
```

---

## ТИПОВЫЕ ЗАДАЧИ

### Создать каталог с фильтрами
1. Создать инфоблок с нужными свойствами
2. Настроить компонент bitrix:catalog.section с фильтром
3. Кастомный шаблон с AJAX-фильтрацией
4. SEF-режим для ЧПУ URL

### Сделать форму с отправкой на email + CRM
1. Создать веб-форму или использовать CRM-форму
2. Настроить почтовый шаблон
3. Добавить обработчик для создания лида в CRM
4. CAPTCHA для защиты от спама

### Настроить поиск по сайту
```php
$APPLICATION->IncludeComponent("bitrix:search.page", "custom", [
    "RESTART" => "Y",
    "NO_WORD_LOGIC" => "Y",
    "SHOW_WHERE" => "Y",
    "PAGE_RESULT_COUNT" => 20,
]);
```
