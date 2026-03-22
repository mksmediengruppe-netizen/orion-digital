"""
Bitrix Configuration - constants and defaults for Bitrix operations.
ULTIMATE PATCH Part D.
"""

# Default Bitrix editions
BITRIX_EDITIONS = {
    "start": {"name": "Start", "code": "start", "trial": True},
    "standard": {"name": "Standard", "code": "standard", "trial": True},
    "small_business": {"name": "Small Business", "code": "small_business", "trial": True},
    "business": {"name": "Business", "code": "business", "trial": True},
}

# Default PHP requirements
PHP_REQUIREMENTS = {
    "min_version": "8.1",
    "extensions": [
        "mbstring", "curl", "gd", "zip", "xml",
        "json", "opcache", "mysql", "intl"
    ]
}

# Default MySQL settings for Bitrix
MYSQL_DEFAULTS = {
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
    "innodb_buffer_pool_size": "256M",
    "max_allowed_packet": "64M"
}

# Bitrix setup URLs
BITRIX_SETUP_URL = "https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php"
BITRIX_RESTORE_URL = "https://www.1c-bitrix.ru/download/scripts/restore.php"

# Default paths
DEFAULT_INSTALL_PATH = "/var/www/html"
DEFAULT_UPLOAD_DIR = "upload"
DEFAULT_CACHE_DIR = "bitrix/cache"

# Wizard steps
WIZARD_STEPS = [
    "license_agreement",
    "requirements_check",
    "database_setup",
    "site_settings",
    "module_install",
    "template_select",
    "finish"
]

# Component categories
COMPONENT_CATEGORIES = {
    "content": ["bitrix:news.list", "bitrix:catalog.section", "bitrix:iblock.element.list"],
    "forms": ["bitrix:form.result.new", "bitrix:main.feedback"],
    "navigation": ["bitrix:menu", "bitrix:breadcrumb", "bitrix:search.page"],
    "media": ["bitrix:photo.section", "bitrix:player"],
    "commerce": ["bitrix:catalog", "bitrix:sale.basket.basket", "bitrix:sale.order.ajax"],
}
