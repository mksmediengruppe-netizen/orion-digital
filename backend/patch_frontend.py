#!/usr/bin/env python3
"""
Патч frontend/app.js:
1. Добавить обработку SSE event 'browser_takeover' в _handleSSE
2. Добавить BrowserTakeover UI компонент (скриншот + инструкция + кнопки)
3. Добавить emoji для новых инструментов
"""

APP_JS = "/var/www/orion/frontend/app.js"

with open(APP_JS, "r") as f:
    content = f.read()

# ═══════════════════════════════════════════════════════════════
# 1. Добавить case 'browser_takeover' в _handleSSE (после auth_required)
# ═══════════════════════════════════════════════════════════════

old_auth_case = """            case 'auth_required':
                // ПАТЧ ЗАДАЧА-1: browser_ask_auth — безопасная авторизация
                AuthForm.show(evt);
                break;"""

new_auth_case = """            case 'auth_required':
                // ПАТЧ ЗАДАЧА-1: browser_ask_auth — безопасная авторизация
                AuthForm.show(evt);
                break;
            case 'browser_takeover':
                // ПАТЧ: browser_ask_user — передача управления пользователю
                BrowserTakeover.show(evt);
                break;"""

if old_auth_case in content:
    content = content.replace(old_auth_case, new_auth_case, 1)
    print("[OK] Added browser_takeover case in _handleSSE")
else:
    print("[WARN] Could not find auth_required case")

# ═══════════════════════════════════════════════════════════════
# 2. Добавить emoji для новых инструментов
# ═══════════════════════════════════════════════════════════════

old_emoji = """            browser_submit: '📨', browser_select: '📋', browser_ask_auth: '🔐',"""

new_emoji = """            browser_submit: '📨', browser_select: '📋', browser_ask_auth: '🔐',
            browser_type: '⌨️', browser_js: '💻', browser_press_key: '⏎',
            browser_scroll: '📜', browser_hover: '🖱️', browser_wait: '⏳',
            browser_elements: '🔍', browser_screenshot: '📸', browser_page_info: 'ℹ️',
            smart_login: '🔑', browser_ask_user: '🙋', browser_takeover_done: '✅',"""

if old_emoji in content:
    content = content.replace(old_emoji, new_emoji, 1)
    print("[OK] Added emoji for new tools")
else:
    print("[WARN] Could not find emoji map")

# ═══════════════════════════════════════════════════════════════
# 3. Добавить BrowserTakeover компонент (перед window.Chat = Chat)
# ═══════════════════════════════════════════════════════════════

TAKEOVER_COMPONENT = '''
// ═════════════════════════════════════════════════════════════
// ПАТЧ: BrowserTakeover — передача управления браузером пользователю
// Когда агент встречает CAPTCHA, 2FA, или не может залогиниться,
// он показывает скриншот и просит пользователя помочь.
// Пользователь может: ввести данные в чат, или нажать "Готово" когда закончит.
// ═════════════════════════════════════════════════════════════
const BrowserTakeover = {
    show(evt) {
        const container = document.querySelector('.chat-messages, #chat-messages, .messages-list, #messages-container, .messages-container');
        if (!container) return;

        const reason = evt.reason || 'custom';
        const reasonLabels = {
            'captcha': '🤖 Обнаружена CAPTCHA',
            '2fa': '🔐 Требуется двухфакторная аутентификация',
            'login_failed': '❌ Автоматический вход не удался',
            'unusual_form': '🔍 Необычная форма входа',
            'confirmation': '⚠️ Требуется подтверждение',
            'custom': '🙋 Требуется ваше участие'
        };

        const screenshotHtml = evt.screenshot
            ? `<div class="takeover-screenshot"><img src="data:image/png;base64,${evt.screenshot}" alt="Текущая страница" style="max-width:100%;border-radius:8px;border:1px solid var(--border-color);margin-bottom:12px;cursor:pointer;" onclick="Lightbox.show(this.src)"></div>`
            : (evt.screenshot_url 
                ? `<div class="takeover-screenshot"><img src="${evt.screenshot_url}" alt="Текущая страница" style="max-width:100%;border-radius:8px;border:1px solid var(--border-color);margin-bottom:12px;cursor:pointer;" onclick="Lightbox.show(this.src)"></div>`
                : '');

        const instruction = evt.instruction || evt.message || 'Пожалуйста, выполните действие вручную и нажмите "Готово"';

        const actionsHtml = (evt.actions || []).map(a => {
            if (a.type === 'input') {
                return `<div class="takeover-field">
                    <label class="auth-label">${a.label || a.name}</label>
                    <input type="${a.input_type || 'text'}" class="auth-input form-input takeover-input" 
                           data-field-name="${a.name}" placeholder="${a.placeholder || ''}">
                </div>`;
            }
            return '';
        }).join('');

        const card = document.createElement('div');
        card.className = 'browser-takeover-card';
        card.innerHTML = `
            <div class="takeover-header">
                <span class="takeover-title">${reasonLabels[reason] || reasonLabels['custom']}</span>
            </div>
            ${evt.url ? `<div class="takeover-url">${evt.url}</div>` : ''}
            ${screenshotHtml}
            <div class="takeover-instruction">${instruction}</div>
            ${actionsHtml}
            <div class="takeover-actions">
                <button class="btn-secondary takeover-skip">Пропустить</button>
                ${actionsHtml ? '<button class="btn-primary takeover-submit-data">📤 Отправить данные</button>' : ''}
                <button class="btn-primary takeover-done">✅ Готово, продолжай</button>
            </div>
        `;

        container.appendChild(card);
        container.scrollTop = container.scrollHeight;

        // Обработчики кнопок
        card.querySelector('.takeover-done').onclick = () => {
            card.style.opacity = '0.5';
            card.querySelector('.takeover-done').textContent = '⏳ Продолжаю...';
            card.querySelector('.takeover-done').disabled = true;
            // Отправляем сообщение агенту что пользователь закончил
            Chat._sendUserMessage('[TAKEOVER_DONE] Пользователь завершил ручной ввод');
        };

        card.querySelector('.takeover-skip').onclick = () => {
            card.remove();
            Chat._sendUserMessage('[TAKEOVER_SKIP] Пользователь пропустил ручной ввод');
        };

        const submitBtn = card.querySelector('.takeover-submit-data');
        if (submitBtn) {
            submitBtn.onclick = () => {
                const inputs = card.querySelectorAll('.takeover-input');
                const data = {};
                inputs.forEach(inp => {
                    data[inp.dataset.fieldName] = inp.value;
                });
                card.style.opacity = '0.5';
                submitBtn.textContent = '⏳ Отправлено...';
                submitBtn.disabled = true;
                Chat._sendUserMessage('[TAKEOVER_DATA] ' + JSON.stringify(data));
            };
        }
    }
};
'''

old_global = "window.Chat = Chat;"
new_global = TAKEOVER_COMPONENT + "\nwindow.BrowserTakeover = BrowserTakeover;\nwindow.Chat = Chat;"

if old_global in content:
    content = content.replace(old_global, new_global, 1)
    print("[OK] Added BrowserTakeover component")
else:
    print("[WARN] Could not find window.Chat = Chat")

# ═══════════════════════════════════════════════════════════════
# 4. Добавить CSS стили для BrowserTakeover
# ═══════════════════════════════════════════════════════════════

STYLE_CSS = "/var/www/orion/frontend/style.css"
try:
    with open(STYLE_CSS, "r") as f:
        css = f.read()
    
    takeover_css = '''
/* ── Browser Takeover Card ─────────────────────────────────── */
.browser-takeover-card {
    background: var(--card-bg, #1e1e2e);
    border: 2px solid #f59e0b;
    border-radius: 12px;
    padding: 16px;
    margin: 12px 0;
    animation: slideIn 0.3s ease;
}
.takeover-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
}
.takeover-title {
    font-weight: 600;
    font-size: 15px;
    color: #f59e0b;
}
.takeover-url {
    font-size: 12px;
    color: var(--text-secondary, #888);
    margin-bottom: 8px;
    word-break: break-all;
}
.takeover-instruction {
    background: rgba(245, 158, 11, 0.1);
    border-left: 3px solid #f59e0b;
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    margin-bottom: 12px;
    font-size: 14px;
    line-height: 1.5;
}
.takeover-screenshot img {
    max-height: 400px;
    object-fit: contain;
}
.takeover-field {
    margin-bottom: 8px;
}
.takeover-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 12px;
}
.takeover-done {
    background: #10b981 !important;
    border-color: #10b981 !important;
}
.takeover-done:hover {
    background: #059669 !important;
}
'''
    
    if '.browser-takeover-card' not in css:
        css += takeover_css
        with open(STYLE_CSS, "w") as f:
            f.write(css)
        print("[OK] Added takeover CSS styles")
    else:
        print("[INFO] Takeover CSS already exists")
except Exception as e:
    print(f"[WARN] Could not update CSS: {e}")

# ═══════════════════════════════════════════════════════════════
# SAVE app.js
# ═══════════════════════════════════════════════════════════════

with open(APP_JS, "w") as f:
    f.write(content)

print(f"\n[DONE] Frontend patched successfully")
print(f"[INFO] app.js size: {len(content)} chars")
