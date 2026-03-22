# База знаний: Хостинги и DNS управление
# Версия: 1.0 | Обновлено: 2025

---

## Beget

**API:** https://api.beget.com/api/
**Панель:** https://cp.beget.com
**Документация:** https://beget.com/ru/kb/api/

### DNS через API (предпочтительно):
```python
import urllib.parse, requests, json

def beget_set_dns(login, password, domain, ip):
    records = {"A": [{"priority": 10, "value": ip}]}
    input_data = json.dumps({"fqdn": domain, "records": records})
    url = (
        f"https://api.beget.com/api/dns/changeRecords"
        f"?login={login}&passwd={urllib.parse.quote(password)}"
        f"&input_format=json&output_format=json"
        f"&input_data={urllib.parse.quote(input_data)}"
    )
    resp = requests.get(url, verify=False, timeout=30)
    return resp.json()

# Пример:
# result = beget_set_dns("asmksm58", "Gfhjkm1234", "asmksm58.beget.tech", "45.67.57.175")
```

### DNS через панель (если API не работает):
1. `browser_navigate` → https://cp.beget.com
2. Логин/пароль
3. Раздел "Домены" → DNS
4. Изменить A-запись

### Определение: `dig NS домен` → ns1.beget.com, ns2.beget.com

---

## Timeweb

**API:** https://api.timeweb.cloud/
**Панель:** https://hosting.timeweb.ru
**Документация:** https://timeweb.cloud/api-docs

### DNS через API:
```python
import requests

def timeweb_set_dns(token, domain, ip):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Получить список записей
    resp = requests.get(f"https://api.timeweb.cloud/api/v1/domains/{domain}/dns-records", headers=headers)
    # Добавить/изменить A-запись
    data = {"type": "A", "value": ip}
    resp = requests.post(f"https://api.timeweb.cloud/api/v1/domains/{domain}/dns-records", json=data, headers=headers)
    return resp.json()
```

### Определение: `dig NS домен` → ns1.timeweb.ru, ns2.timeweb.ru

---

## REG.RU

**API:** https://api.reg.ru/api/regru2/
**Панель:** https://www.reg.ru/user/account
**Документация:** https://www.reg.ru/support/help/api2

### DNS через API:
```python
import requests

def regru_set_dns(login, password, domain, ip):
    url = "https://api.reg.ru/api/regru2/zone/update_records"
    data = {
        "username": login,
        "password": password,
        "domains": [{"dname": domain}],
        "subdomain": "@",
        "record_type": "A",
        "content": ip,
        "output_content_type": "json"
    }
    resp = requests.post(url, data=data)
    return resp.json()
```

### Определение: `dig NS домен` → ns1.reg.ru, ns2.reg.ru

---

## Selectel

**API:** https://api.selectel.ru/
**Панель:** https://my.selectel.ru
**Документация:** https://developers.selectel.ru/docs/

### DNS через API:
```python
import requests

def selectel_set_dns(token, zone_id, domain, ip):
    headers = {"X-Auth-Token": token, "Content-Type": "application/json"}
    data = {"name": domain + ".", "type": "A", "ttl": 60, "content": ip}
    resp = requests.post(
        f"https://api.selectel.ru/domains/v2/zones/{zone_id}/rrsets/",
        json=data, headers=headers
    )
    return resp.json()
```

### Определение: `dig NS домен` → ns1.selectel.org, ns2.selectel.org

---

## Hetzner

**API:** https://dns.hetzner.com/api/v1
**Панель:** https://console.hetzner.cloud
**Документация:** https://dns.hetzner.com/api-docs

### DNS через API:
```python
import requests

def hetzner_set_dns(token, zone_id, domain, ip):
    headers = {"Auth-API-Token": token, "Content-Type": "application/json"}
    data = {"value": ip, "ttl": 60, "type": "A", "name": "@", "zone_id": zone_id}
    resp = requests.post("https://dns.hetzner.com/api/v1/records", json=data, headers=headers)
    return resp.json()
```

### Определение: `dig NS домен` → hydrogen.ns.hetzner.com, helium.ns.hetzner.com

---

## DigitalOcean

**API:** https://api.digitalocean.com/v2/
**Панель:** https://cloud.digitalocean.com
**Документация:** https://docs.digitalocean.com/reference/api/

### DNS через API:
```python
import requests

def do_set_dns(token, domain, ip):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = {"type": "A", "name": "@", "data": ip, "ttl": 30}
    resp = requests.post(
        f"https://api.digitalocean.com/v2/domains/{domain}/records",
        json=data, headers=headers
    )
    return resp.json()
```

### Определение: `dig NS домен` → ns1.digitalocean.com, ns2.digitalocean.com

---

## Cloudflare

**API:** https://api.cloudflare.com/client/v4/
**Панель:** https://dash.cloudflare.com
**Документация:** https://developers.cloudflare.com/api/

### DNS через API:
```python
import requests

def cloudflare_set_dns(token, zone_id, domain, ip):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Получить существующие записи
    resp = requests.get(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A&name={domain}",
        headers=headers
    )
    records = resp.json().get("result", [])
    if records:
        # Обновить существующую
        record_id = records[0]["id"]
        data = {"type": "A", "name": domain, "content": ip, "ttl": 1, "proxied": False}
        resp = requests.put(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}",
            json=data, headers=headers
        )
    else:
        # Создать новую
        data = {"type": "A", "name": domain, "content": ip, "ttl": 1, "proxied": False}
        resp = requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
            json=data, headers=headers
        )
    return resp.json()
```

### Определение: `dig NS домен` → *.ns.cloudflare.com

---

## УНИВЕРСАЛЬНЫЙ АЛГОРИТМ ДЛЯ ЛЮБОГО ХОСТИНГА

### Шаг 1: Определить хостинг
```bash
# Определить DNS-серверы домена
dig NS example.com +short

# Определить регистратора
whois example.com | grep -i "registrar\|name server"
```

### Шаг 2: Попробовать API
1. Найти API документацию: `web_search "[хостинг] API DNS documentation"`
2. Прочитать документацию: `web_fetch [URL документации]`
3. Выполнить API запрос через Python

### Шаг 3: Если API не работает — панель управления
1. `browser_navigate` → URL панели
2. Авторизоваться (логин/пароль из настроек)
3. Найти раздел DNS/Домены
4. Изменить A-запись на нужный IP

### Шаг 4: Проверить результат
```bash
# Проверить что DNS обновился (ждать 2-5 минут)
dig +short example.com
nslookup example.com
```

### Шаг 5: Если ничего не помогло
- Спросить пользователя URL панели управления
- Попросить API токен или данные для входа

---

## ПРАВИЛА DNS

1. **A-запись** — указывает домен на IPv4 адрес
2. **AAAA-запись** — указывает домен на IPv6 адрес
3. **CNAME-запись** — псевдоним домена
4. **TTL** — время кэширования (рекомендуется 60-300 секунд при изменениях)
5. **Propagation** — распространение изменений DNS занимает 2-48 часов (обычно 5-15 минут)

---

## ЧАСТЫЕ ОШИБКИ

| Ошибка | Причина | Решение |
|--------|---------|---------|
| 403 Forbidden | Нет прав или неверный токен | Проверить API ключ |
| DNS не меняется | Кэш DNS | Подождать 5-15 минут |
| Сайт не открывается | nginx не настроен | Проверить nginx конфиг |
| Connection refused | Порт закрыт | Открыть порт в firewall |
