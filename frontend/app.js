
/* ── PROJECT TEMPLATES ────────────────────────────────── */
const PROJECT_TEMPLATES = [
    { icon: '🏪', name: 'Интернет-магазин', prompt: 'Создай интернет-магазин с каталогом товаров, корзиной, оформлением заказа и интеграцией платёжной системы' },
    { icon: '🏢', name: 'Корпоративный сайт', prompt: 'Создай корпоративный сайт компании: главная, о компании, услуги, портфолио, контакты, блог' },
    { icon: '📱', name: 'Лендинг + CRM', prompt: 'Создай лендинг с формой заявки и интеграцией Битрикс24 для приёма лидов' },
    { icon: '🤖', name: 'Telegram бот', prompt: 'Создай Telegram бота для приёма заявок с уведомлениями менеджеру' },
    { icon: '📊', name: 'Дашборд аналитики', prompt: 'Создай дашборд для визуализации данных из CSV/Excel с графиками и фильтрами' },
    { icon: '⚡', name: 'n8n Автоматизация', prompt: 'Настрой автоматизацию: форма на сайте → лид в Б24 → задача менеджеру → уведомление в Telegram' },
];

/* ============================================================
   ORION Digital v1.4 — app.js
   Чистый JS: Auth, Chat, SSE Streaming, Activity Panel,
   Admin Panel, Artifacts, Drag&Drop, Theme, Queue
   ============================================================ */

'use strict';

/* ── CONSTANTS ────────────────────────────────────────────── */
const API_BASE = '/api';
const SSE_TIMEOUT = 120000;

const MODES = {
    'turbo-basic':   { label: 'Turbo Обычный',  tag: 'TURBO', desc: 'Быстрые ответы, DeepSeek V3. Идеально для задач разработки.' },
    'turbo-premium': { label: 'Turbo Премиум',  tag: 'PRO',   desc: 'Turbo + Claude Sonnet. Лучшее качество для сложных задач.' },
    'pro-basic':     { label: 'Pro Обычный',    tag: 'AGENT', desc: 'Агентный режим с инструментами. SSH, браузер, файлы.' },
    'pro-premium':   { label: 'Pro Премиум',    tag: 'ELITE', desc: 'Мультиагент: Designer + Developer + DevOps одновременно.' },
    'architect':     { label: 'Architect',        tag: 'OPUS',  desc: 'Claude Opus 4. Архитектура, глубокий анализ, аудит кода.' }
};

/* ── MODE_INFO (УЛУЧ-3) ──────────────────────────────────── */
const MODE_INFO = {
    'turbo-basic':    { text: 'Быстрые ответы · DeepSeek V3 · Экономичный', icon: '⚡' },
    'turbo_basic':    { text: 'Быстрые ответы · DeepSeek V3 · Экономичный', icon: '⚡' },
    'turbo-premium':  { text: 'Sonnet общение · DeepSeek работа · Умный и дешёвый', icon: '✨' },
    'turbo_premium':  { text: 'Sonnet общение · DeepSeek работа · Умный и дешёвый', icon: '✨' },
    'pro-basic':      { text: 'Sonnet планирует · DeepSeek исполняет · Качество', icon: '🧠' },
    'pro_basic':      { text: 'Sonnet планирует · DeepSeek исполняет · Качество', icon: '🧠' },
    'pro-premium':    { text: 'Claude Sonnet 4.6 · Максимум качества', icon: '🚀' },
    'pro_premium':    { text: 'Claude Sonnet 4.6 · Максимум качества', icon: '🚀' },
    'architect':      { text: 'Claude Opus 4 · Архитектор · Для сложных задач', icon: '🏛' },
};

const WELCOME_CHIPS = [
    'Создай лендинг для SaaS продукта',
    'Разверни Docker контейнер на сервере',
    'Напиши Python скрипт для парсинга',
    'Настрой nginx с SSL сертификатом',
    'Сделай REST API на FastAPI',
    'Проанализируй логи и найди ошибки',
    'Покажи, как использовать новые функции Chart.js и артефактов.',
    'Продемонстрируй работу Claude Opus в режиме архитектора.'
];

const MODEL_TAGS = [
    { name: 'DeepSeek V3', color: '#3B82F6' },
    { name: 'Claude Sonnet', color: '#8B5CF6' },
    { name: 'Gemini Pro', color: '#10B981' }
];

/* ── STATE ────────────────────────────────────────────────── */
const state = {
    user: null,
    token: null,
    chats: [],
    currentChatId: null,
    messages: [],
    mode: 'turbo-basic',
    theme: 'light',
    isStreaming: false,
    streamController: null,
    messageQueue: [],
    attachments: [],
    activityVisible: false,
    activityLines: [],
    taskProgress: { current: 0, total: 0, steps: [] },
    totalCost: 0,
    monthlyLimit: 2.00,
    adminData: { users: [], chats: [], analytics: null }
};

/* ── DOM REFS ─────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);
const el = (tag, cls, html) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
};

/* ── UTILS ────────────────────────────────────────────────── */
const Utils = {
    formatTime(date = new Date()) {
        return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },
    formatDate(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return '';
        const now = new Date();
        const diff = now - d;
        if (diff < 60000) return 'только что';
        if (diff < 3600000) return Math.floor(diff / 60000) + ' мин назад';
        if (diff < 86400000) return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        if (diff < 172800000) return 'вчера';
        return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
    },
    formatCost(n) {
        // КРИТ-2 FIX: умное форматирование — 6 знаков для малых сумм
        const v = parseFloat(n);
        if (!n || isNaN(v) || v === 0) return '$0.000';
        if (v < 0.001) return '$' + v.toFixed(6);   // $0.000043
        if (v < 0.01)  return '$' + v.toFixed(5);   // $0.00432
        if (v < 0.1)   return '$' + v.toFixed(4);   // $0.0432
        return '$' + v.toFixed(3);                   // $0.432
    },
    formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1048576).toFixed(1) + ' MB';
    },
    formatDuration(ms) {
        if (ms < 1000) return ms + 'мс';
        if (ms < 60000) return (ms / 1000).toFixed(1) + 'с';
        const m = Math.floor(ms / 60000);
        const s = Math.floor((ms % 60000) / 1000);
        return m + ':' + String(s).padStart(2, '0');
    },
    escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },
    copyText(text) {
        if (navigator.clipboard) {
            return navigator.clipboard.writeText(text);
        }
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        return Promise.resolve();
    },
    debounce(fn, ms) {
        let t;
        return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
    },
    generateId() {
        return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
    },
    groupChatsByDate(chats) {
        const groups = { today: [], yesterday: [], week: [], earlier: [] };
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today - 86400000);
        const weekAgo = new Date(today - 7 * 86400000);
        chats.forEach(chat => {
            const d = new Date(chat.updated_at || chat.created_at);
            if (d >= today) groups.today.push(chat);
            else if (d >= yesterday) groups.yesterday.push(chat);
            else if (d >= weekAgo) groups.week.push(chat);
            else groups.earlier.push(chat);
        });
        return groups;
    },
    getFileIcon(name) {
        const ext = name.split('.').pop().toLowerCase();
        const icons = {
            pdf: '📄', doc: '📝', docx: '📝', txt: '📄',
            js: '💻', ts: '💻', py: '🐍', html: '🌐', css: '🎨',
            json: '📋', xml: '📋', csv: '📊', xlsx: '📊',
            png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', svg: '🖼️', webp: '🖼️',
            zip: '📦', tar: '📦', gz: '📦',
            mp4: '🎬', mp3: '🎵', wav: '🎵'
        };
        return icons[ext] || '📎';
    },
    isImage(name) {
        return /\.(png|jpg|jpeg|gif|svg|webp|bmp)$/i.test(name);
    }
};

/* ── API ──────────────────────────────────────────────────── */
const API = {
    async request(method, path, body, isFormData = false) {
        const headers = {};
        if (state.token) headers['Authorization'] = 'Bearer ' + state.token;
        if (!isFormData && body) headers['Content-Type'] = 'application/json';

        const opts = { method, headers };
        if (body) opts.body = isFormData ? body : JSON.stringify(body);

        const res = await fetch(API_BASE + path, opts);
        if (res.status === 401) {
            Auth.logout();
            throw new Error('Unauthorized');
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Ошибка сервера' }));
            throw new Error(err.detail || 'Ошибка ' + res.status);
        }
        return res.json();
    },
    get: (path) => API.request('GET', path),
    post: (path, body) => API.request('POST', path, body),
    put: (path, body) => API.request('PUT', path, body),
    delete: (path) => API.request('DELETE', path),

    async login(username, password) {
        const res = await fetch(API_BASE + '/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: username, password })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || err.detail || 'Неверный логин или пароль');
        }
        const data = await res.json();
        // Normalize: backend returns {token, user}, frontend expects {access_token}
        if (data.token && !data.access_token) data.access_token = data.token;
        return data;
    },

    async uploadFile(file) {
        const fd = new FormData();
        fd.append('file', file);
        return API.request('POST', '/files/upload', fd, true);
    }
};

/* ── AUTH ─────────────────────────────────────────────────── */
const Auth = {
    init() {
        const token = localStorage.getItem('orion_token');
        const user = localStorage.getItem('orion_user');
        if (token && user) {
            state.token = token;
            state.user = JSON.parse(user);
            this.onLogin();
        } else {
            this.showAuthScreen();
        }
    },

    showAuthScreen() {
        $('auth-screen').classList.remove('hidden');
        $('app').classList.add('hidden');
    },

    hideAuthScreen() {
        $('auth-screen').classList.add('hidden');
        $('app').classList.remove('hidden');
    },

    async handleLogin(e) {
        e.preventDefault();
        const username = $('auth-login').value.trim();
        const password = $('auth-password').value;
        const errEl = $('auth-error');
        const btn = $('auth-submit');

        if (!username || !password) {
            errEl.textContent = 'Введите логин и пароль';
            errEl.classList.add('visible');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner spinner-sm"></span> Вход...';
        errEl.classList.remove('visible');

        try {
            const data = await API.login(username, password);
            state.token = data.access_token;
            localStorage.setItem('orion_token', data.access_token);

            const me = await API.get('/auth/me');
            state.user = me;
            localStorage.setItem('orion_user', JSON.stringify(me));

            this.onLogin();
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.add('visible');
            btn.disabled = false;
            btn.textContent = 'Войти';
        }
    },

    onLogin() {
        this.hideAuthScreen();
        // FIX: Sync budget from user data on login
        if (state.user) {
            if (state.user.monthly_limit) state.monthlyLimit = state.user.monthly_limit;
            if (state.user.total_spent !== undefined) state.totalCost = state.user.total_spent;
        }
        UI.init();
        ChatList.load();
        UI.updateUserInfo();
        SSHSettings.init();
    },

    logout() {
        state.token = null;
        state.user = null;
        state.chats = [];
        state.currentChatId = null;
        state.messages = [];
        localStorage.removeItem('orion_token');
        localStorage.removeItem('orion_user');
        localStorage.removeItem('orion_theme');
        Theme.set('light');
        this.showAuthScreen();
        $('auth-login').value = '';
        $('auth-password').value = '';
    }
};

/* ── THEME ────────────────────────────────────────────────── */
const Theme = {
    init() {
        // One-time migration: reset dark theme preference
        if (!localStorage.getItem('orion_theme_v2')) {
            localStorage.removeItem('orion_theme');
            localStorage.setItem('orion_theme_v2', '1');
        }
        const saved = localStorage.getItem('orion_theme');
        const theme = saved || 'light';
        this.set(theme);
    },
    toggle() {
        this.set(state.theme === 'light' ? 'dark' : 'light');
    },
    set(theme) {
        state.theme = theme;
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('orion_theme', theme);
        const btn = $('btn-theme');
        if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
        // Toggle highlight.js theme
        const darkHljs = document.querySelector('link[href*="github-dark"]');
        if (darkHljs) darkHljs.disabled = theme !== 'dark';
    }
};

/* ── UI INIT ──────────────────────────────────────────────── */
const UI = {
    init() {
        // ПАТЧ W1-1: Восстановить режим из localStorage
        try {
            const savedMode = localStorage.getItem('orion_mode');
            if (savedMode && ['turbo_basic', 'turbo_premium', 'pro_basic', 'pro_premium'].includes(savedMode)) {
                state.mode = savedMode;
            }
        } catch(e) {}
        this.renderModes();
        this.renderWelcome();
        this.bindEvents();
        Theme.init();
        ActivityPanel.hide();
    },

    renderModes() {
        const grid = document.querySelector('.modes-grid, .mode-grid');
        if (!grid) return;
        grid.innerHTML = '';
        Object.entries(MODES).forEach(([key, m]) => {
            const btn = el('button', 'mode-btn' + (key === state.mode ? ' active' : ''));
            btn.dataset.mode = key;
            btn.innerHTML = `<span class="mode-name">${m.label}</span><span class="mode-tag">${m.tag}</span>`;
            btn.addEventListener('click', () => this.setMode(key));
            // УЛУЧ-3: показывать MODE_INFO при наведении
            btn.addEventListener('mouseenter', () => this.showModeInfo(key));
            btn.addEventListener('mouseleave', () => this.showModeInfo(state.mode));
            grid.appendChild(btn);
        });
        this.updateModeDesc();
        this.renderModeInfoBar();
    },

    renderModeInfoBar() {
        // Используем существующий #mode-description или создаём mode-info-bar
        let infoBar = document.getElementById('mode-info-bar') || document.getElementById('mode-description');
        if (!infoBar) {
            const grid = document.querySelector('.modes-grid, .mode-grid');
            if (!grid) return;
            infoBar = document.createElement('div');
            infoBar.id = 'mode-info-bar';
            infoBar.className = 'mode-info-bar';
            grid.parentElement.insertBefore(infoBar, grid.nextSibling);
        } else if (!infoBar.id || infoBar.id === 'mode-description') {
            infoBar.id = 'mode-info-bar';
            infoBar.classList.add('mode-info-bar');
        }
        this.showModeInfo(state.mode);
        // ПАТЧ W1-1: Подсветить восстановленный режим
        $$('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === state.mode));
    },

    showModeInfo(key) {
        const infoBar = document.getElementById('mode-info-bar');
        if (!infoBar) return;
        const info = MODE_INFO[key];
        if (info) {
            infoBar.innerHTML = `<span class="mode-info-icon">${info.icon}</span><span class="mode-info-text">${info.text}</span>`;
            infoBar.style.opacity = '1';
        } else {
            // Fallback: показываем desc из MODES
            const modeData = MODES[key];
            if (modeData) {
                infoBar.innerHTML = `<span class="mode-info-text">${modeData.desc || ''}</span>`;
            }
        }
    },

    setMode(key) {
        state.mode = key;
        try { localStorage.setItem('orion_mode', key); } catch(e) {}
        $$('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === key));
        this.updateModeDesc();
        this.updateFooterInfo();
        this.showModeInfo(key);  // УЛУЧ-3: обновить инфо-бар при выборе
        // Improvement 3: Update model label on mode switch
        const MODEL_LABELS = {
            'turbo-basic': 'DeepSeek V3',
            'turbo-premium': 'Claude Sonnet',
            'pro-basic': 'DeepSeek V3 + Sonnet',
            'pro-premium': 'Claude Sonnet',
            'architect': 'Claude Opus 4'
        };
        const modelLabel = document.querySelector('.header-model, .model-label, [data-model]');
        if (modelLabel) modelLabel.textContent = MODEL_LABELS[key] || 'DeepSeek V3';
    },

    updateModeDesc() {
        const desc = document.querySelector('.mode-description');
        if (desc) desc.textContent = MODES[state.mode]?.desc || '';
    },

    renderWelcome() {
        const msgs = $('messages-container');
        if (!msgs) return;
        msgs.innerHTML = '';
        const ws = el('div', 'welcome-screen');
        ws.innerHTML = `
            <div class="welcome-logo">
                <div class="welcome-logo-title">
                    <span class="logo-text-big">ORION</span>
                    <span class="logo-sub-big">Digital</span>
                </div>
            </div>
            <p class="welcome-subtitle">Мультиагентная AI-система нового поколения</p>
            <div class="welcome-chips">
                ${WELCOME_CHIPS.map(c => `<button class="welcome-chip" data-prompt="${c.replace(/"/g, '&quot;')}">${c}</button>`).join('')}
            </div>
            <div class="welcome-models">
                ${MODEL_TAGS.map(m => `<div class="model-tag"><span class="model-tag-dot" style="background:${m.color}"></span>${m.name}</div>`).join('')}
            </div>
            <div style="margin-top:16px;text-align:center">
                <button class="welcome-templates-btn">📋 Посмотреть шаблоны проектов</button>
            </div>`;
        msgs.appendChild(ws);
        // Bind chip click handlers after DOM insertion
        ws.querySelectorAll('.welcome-chip[data-prompt]').forEach(btn => {
            btn.addEventListener('click', () => Chat.sendFromChip(btn.dataset.prompt));
        });
        const tplBtn = ws.querySelector('.welcome-templates-btn');
        if (tplBtn && typeof Templates !== 'undefined') tplBtn.addEventListener('click', () => Templates.open());
    },

    updateUserInfo() {
        const u = state.user;
        if (!u) return;
        // FIX: Sync monthlyLimit and totalCost from user data
        if (u.monthly_limit) state.monthlyLimit = u.monthly_limit;
        if (u.total_spent !== undefined) state.totalCost = u.total_spent;
        const nameEl = document.querySelector('.user-name');
        const roleEl = document.querySelector('.user-role');
        const avatarEl = document.querySelector('.user-avatar');
        if (nameEl) nameEl.textContent = u.full_name || u.username;
        if (roleEl) roleEl.textContent = u.role === 'admin' ? 'Администратор' : 'Пользователь';
        if (avatarEl) avatarEl.textContent = (u.full_name || u.username || 'U')[0].toUpperCase();

        const adminBtn = $('btn-admin');
        if (adminBtn) {
            if (u.role === 'admin') {
                adminBtn.classList.remove('hidden');
                adminBtn.style.display = '';
            } else {
                adminBtn.classList.add('hidden');
                adminBtn.style.display = 'none';
            }
        }

        this.updateCostBar();
    },

    updateCostBar() {
        // BUG-11 FIX: HTML uses id=budget-fill and id=budget-text
        const fill = $('budget-fill') || document.querySelector('.cost-bar-fill, .budget-fill');
        const val = $('budget-text') || document.querySelector('.cost-bar-value, .budget-value');
        if (!fill && !val) return;
        const pct = Math.min(100, (state.totalCost / (state.monthlyLimit || 2)) * 100);
        if (fill) {
            fill.style.width = pct + '%';
            fill.className = (fill.id === 'budget-fill' ? 'budget-fill' : 'cost-bar-fill') + (pct > 80 ? ' danger' : pct > 50 ? ' warn' : '');
        }
        if (val) val.textContent = Utils.formatCost(state.totalCost) + ' / $' + (state.monthlyLimit || 2).toFixed(2);
    },

    updateFooterInfo() {
        const info = document.querySelector('.input-footer-info') || document.getElementById('input-footer-text');
        if (info) {
            const mode = MODES[state.mode];
            const chatCost = state.currentChatCost || 0;
            info.textContent = `ORION Digital · ${mode?.label || ''} · $${chatCost.toFixed(3)} за чат`;
        }
        // Also update budget elements
        const budgetEl = document.querySelector('.sidebar-budget-current, .budget-current');
        if (budgetEl) budgetEl.textContent = '$' + (state.currentChatCost || 0).toFixed(2);
    },

    updateChatTitle(title) {
        // BUG-5 FIX: HTML uses id="chat-title" (h1 contenteditable), not chat-title-input
        const el = $('chat-title');
        if (el) el.textContent = title || 'Новый чат';
    },

    setStreaming(active) {
        state.isStreaming = active;
        const sendBtn = $('btn-send');
        const stopBtn = $('btn-stop');
        // Используем classList вместо style.display — класс hidden имеет !important
        if (sendBtn) {
            if (active) {
                sendBtn.classList.add('hidden');
            } else {
                sendBtn.classList.remove('hidden');
                sendBtn.style.display = '';
            }
        }
        if (stopBtn) {
            if (active) {
                stopBtn.classList.remove('hidden');
                stopBtn.style.display = 'flex';
            } else {
                stopBtn.classList.add('hidden');
                stopBtn.style.display = '';
            }
        }
        const textarea = $('message-input');
        if (textarea) textarea.placeholder = active ? 'Можно писать — сообщение встанет в очередь...' : 'Напишите сообщение...';
    },

    showQueueIndicator(count) {
        let qi = document.querySelector('.queue-indicator');
        if (count > 0) {
            if (!qi) {
                qi = el('div', 'queue-indicator');
                qi.style.cssText = 'padding: 6px 12px; background: var(--bg-hover, #1e1e2e); border-radius: 8px; margin-bottom: 6px; font-size: 12px;';
                const inputArea = document.querySelector('.chat-input-area');
                if (inputArea) inputArea.insertBefore(qi, inputArea.firstChild);
            }
            // ПАТЧ W1-4: Расширенная очередь с кнопкой очистки
            let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                <span>⏳ В очереди: ${count}</span>
                <button onclick="state.messageQueue=[];UI.showQueueIndicator(0)" style="background:none;border:none;color:#f87171;cursor:pointer;font-size:11px;">Очистить</button>
            </div>`;
            state.messageQueue.forEach((item, i) => {
                const preview = (item.text || '').substring(0, 60) + ((item.text || '').length > 60 ? '...' : '');
                const priority = item.priority ? ' ⚡' : '';
                html += `<div style="display:flex;align-items:center;gap:6px;padding:2px 0;font-size:11px;color:var(--text-secondary);">
                    <span>${i+1}. ${priority}${preview}</span>
                    <button onclick="state.messageQueue.splice(${i},1);UI.showQueueIndicator(state.messageQueue.length)" style="background:none;border:none;color:#f87171;cursor:pointer;font-size:10px;">✕</button>
                </div>`;
            });
            qi.innerHTML = html;
        } else if (qi) {
            qi.remove();
        }
    },

    bindEvents() {
        // Auth form
        const authForm = $('auth-form');
        if (authForm) authForm.addEventListener('submit', e => Auth.handleLogin(e));

        // УЛУЧ-3: Привязываем hover к HTML-кнопкам режимов (если они уже в DOM)
        setTimeout(() => {
            $$('.mode-btn[data-mode]').forEach(btn => {
                const key = btn.dataset.mode;
                if (!btn._modeInfoBound) {
                    btn.addEventListener('mouseenter', () => UI.showModeInfo(key));
                    btn.addEventListener('mouseleave', () => UI.showModeInfo(state.mode));
                    btn._modeInfoBound = true;
                }
            });
            UI.renderModeInfoBar();
        }, 100);

        // New chat
        const newChatBtn = $('btn-new-chat');
        if (newChatBtn) newChatBtn.addEventListener('click', () => Chat.newChat());

        // Theme toggle
        const themeBtn = $('btn-theme');
        if (themeBtn) themeBtn.addEventListener('click', () => Theme.toggle());

        // Logout
        const logoutBtn = $('btn-logout');
        if (logoutBtn) logoutBtn.addEventListener('click', () => Auth.logout());

        // Admin
        const adminBtn = $('btn-admin');
        if (adminBtn) adminBtn.addEventListener('click', () => AdminPanel.open());

        // Chat input
        const textarea = $('message-input');
        if (textarea) {
            textarea.addEventListener('keydown', e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    Chat.send();
                }
            });
            textarea.addEventListener('input', () => {
                this.autoResize(textarea);
                // ══ DRAFT PERSISTENCE: save draft to sessionStorage ══
                if (state.currentChatId) {
                    const val = textarea.value;
                    if (val) {
                        sessionStorage.setItem('draft_' + state.currentChatId, val);
                    } else {
                        sessionStorage.removeItem('draft_' + state.currentChatId);
                    }
                }
            });
        }

        // Send button
        const sendBtn = $('btn-send');
        if (sendBtn) sendBtn.addEventListener('click', () => Chat.send());

        // Stop button
        const stopBtn = $('btn-stop');
        if (stopBtn) stopBtn.addEventListener('click', () => Chat.stop());

        // Settings modal
        const settingsBtn = $('btn-settings');
        const settingsModal = $('settings-modal');
        const settingsClose = $('btn-settings-close');
        if (settingsBtn && settingsModal) {
            settingsBtn.addEventListener('click', () => settingsModal.classList.remove('hidden'));
        }
        if (settingsClose && settingsModal) {
            settingsClose.addEventListener('click', () => settingsModal.classList.add('hidden'));
        }
        if (settingsModal) {
            settingsModal.addEventListener('click', (e) => {
                if (e.target === settingsModal) settingsModal.classList.add('hidden');
            });
        }

        // Attach button
        const attachBtn = $('btn-attach');
        const fileInput = $('file-input');
        if (attachBtn && fileInput) {
            attachBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', e => Attachments.handleFiles(e.target.files));
        }

        // Chat title rename (BUG-5 FIX: id=chat-title, contenteditable)
        const titleInput = $('chat-title');
        if (titleInput) {
            titleInput.addEventListener('blur', () => Chat.renameCurrentChat(titleInput.textContent));
            titleInput.addEventListener('keydown', e => {
                if (e.key === 'Enter') titleInput.blur();
                if (e.key === 'Escape') {
                    titleInput.value = state.chats.find(c => c.id === state.currentChatId)?.title || 'Новый чат';
                    titleInput.blur();
                }
            });
        }

        // Drag & Drop
        const chatArea = $('chat-area');
        if (chatArea) {
            chatArea.addEventListener('dragover', e => { e.preventDefault(); Attachments.showDropOverlay(); });
            chatArea.addEventListener('dragleave', e => { if (!chatArea.contains(e.relatedTarget)) Attachments.hideDropOverlay(); });
            chatArea.addEventListener('drop', e => { e.preventDefault(); Attachments.handleFiles(e.dataTransfer.files); Attachments.hideDropOverlay(); });
        }

        // ══ PATCH 5: Rename button handler ══
        const editTitleBtn = $('btn-edit-title');
        if (editTitleBtn) {
            editTitleBtn.addEventListener('click', () => {
                const titleEl = $('chat-title');
                if (!titleEl || !state.currentChatId) return;
                titleEl.contentEditable = 'true';
                titleEl.focus();
                // Select all text
                const range = document.createRange();
                range.selectNodeContents(titleEl);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                // Style to show it's editable
                titleEl.style.outline = '2px solid #d4af37';
                titleEl.style.borderRadius = '4px';
                titleEl.style.padding = '2px 6px';
                const finishEdit = () => {
                    titleEl.contentEditable = 'false';
                    titleEl.style.outline = '';
                    titleEl.style.borderRadius = '';
                    titleEl.style.padding = '';
                    const newTitle = titleEl.textContent.trim();
                    if (newTitle) Chat.renameCurrentChat(newTitle);
                    titleEl.removeEventListener('blur', finishEdit);
                    titleEl.removeEventListener('keydown', handleKey);
                };
                const handleKey = (e) => {
                    if (e.key === 'Enter') { e.preventDefault(); titleEl.blur(); }
                    if (e.key === 'Escape') {
                        const chat = state.chats.find(c => c.id === state.currentChatId);
                        titleEl.textContent = chat ? chat.title : 'Новый чат';
                        titleEl.blur();
                    }
                };
                titleEl.addEventListener('blur', finishEdit);
                titleEl.addEventListener('keydown', handleKey);
            });
        }
        // Activity panel toggle
        const activityToggle = $('btn-activity-toggle');
        if (activityToggle) activityToggle.addEventListener('click', () => ActivityPanel.toggle());

        // Collapse activity
        const collapseBtn = $('btn-collapse-activity');
        if (collapseBtn) collapseBtn.addEventListener('click', () => ActivityPanel.hide());

        // Sidebar toggle (mobile)
        const sidebarToggle = $('btn-sidebar-toggle');
        if (sidebarToggle) sidebarToggle.addEventListener('click', () => Sidebar.toggle());

        // Sidebar overlay
        const overlay = $('sidebar-overlay');
        if (overlay) overlay.addEventListener('click', () => Sidebar.close());

        // Search
        const searchInput = $('chat-search');
        if (searchInput) searchInput.addEventListener('input', Utils.debounce(e => ChatList.filter(e.target.value), 200));

        // Lightbox close
        const lightbox = $('lightbox');
        if (lightbox) {
            lightbox.addEventListener('click', e => {
                if (e.target === lightbox || e.target.classList.contains('lightbox-close')) {
                    Lightbox.close();
                }
            });
        }

        // Takeover send
        const takeoverBtn = $('btn-takeover-send');
        if (takeoverBtn) takeoverBtn.addEventListener('click', () => ActivityPanel.sendTakeover());

        // Templates button
        const templatesBtn = $('btn-templates');
        if (templatesBtn) templatesBtn.addEventListener('click', () => Templates.open());

        // Welcome chips (data-prompt buttons in HTML) — only static chips in index.html
        document.querySelectorAll('#welcome-chips .welcome-chip[data-prompt]').forEach(btn => {
            btn.addEventListener('click', () => Chat.sendFromChip(btn.dataset.prompt));
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                Lightbox.close();
                AdminPanel.close();
                Sidebar.close();
                Templates.close();
            }
        });
    },

    autoResize(textarea) {
        textarea.style.height = 'auto';
        const maxH = 144;
        textarea.style.height = Math.min(textarea.scrollHeight, maxH) + 'px';
    }
};

/* ── SIDEBAR ──────────────────────────────────────────────── */
const Sidebar = {
    toggle() {
        const sb = $('sidebar');
        if (sb) sb.classList.toggle('open');
        const ov = $('sidebar-overlay');
        if (ov) ov.classList.toggle('visible', sb.classList.contains('open'));
    },
    close() {
        const sb = $('sidebar');
        if (sb) sb.classList.remove('open');
        const ov = $('sidebar-overlay');
        if (ov) ov.classList.remove('visible');
    }
};

/* ── CHAT LIST ────────────────────────────────────────────── */
const ChatList = {
    async load() {
        try {
            const data = await API.get('/chats');
            // Normalize: backend may return [{chat: {...}}, ...] or [{id, ...}, ...]
            const rawChats = data.chats || data || [];
            state.chats = rawChats.map(c => c.chat || c);
            // FIX CRИТ-2: Инициализируем totalCost из суммы всех чатов при загрузке
            state.totalCost = state.chats.reduce((sum, c) => sum + (c.total_cost || 0), 0);
            UI.updateCostBar();
            this.render();
        } catch (e) {
            console.warn('ChatList.load error:', e);
            // BUG-12 FIX: Don't clear existing chats on load error
            // Only render empty if we never had chats
            if (!state.chats.length) {
                this.render();
            } else {
                Toast.show('Ошибка обновления списка чатов', 'error');
            }
        }
    },

    render(chats = state.chats) {
        const container = $('chat-list');
        if (!container) return;
        container.innerHTML = '';

        if (!chats.length) {
            container.innerHTML = '<div class="empty-state" style="padding:20px"><div class="empty-state-icon">💬</div><div class="empty-state-desc">Нет чатов. Начните новый!</div></div>';
            return;
        }

        const groups = Utils.groupChatsByDate(chats);
        const labels = { today: 'Сегодня', yesterday: 'Вчера', week: 'Эта неделя', earlier: 'Ранее' };

        Object.entries(groups).forEach(([key, items]) => {
            if (!items.length) return;
            const label = el('div', 'chat-group-label', labels[key]);
            container.appendChild(label);
            items.forEach(chat => container.appendChild(this.renderItem(chat)));
        });
    },

    renderItem(chat) {
        const item = el('div', 'chat-item' + (chat.id === state.currentChatId ? ' active' : ''));
        item.dataset.chatId = chat.id;
        item.innerHTML = `
            <div class="chat-item-icon">💬</div>
            <div class="chat-item-body">
                <div class="chat-item-title">${Utils.escapeHtml(chat.title || 'Новый чат')}</div>
                <div class="chat-item-meta">
                    <span class="chat-item-cost">${Utils.formatCost(chat.total_cost)}</span>
                    <span class="chat-item-time">${Utils.formatDate(chat.updated_at || chat.created_at)}</span>
                </div>
            </div>
            <div class="chat-item-actions">
                <button class="chat-action-btn" title="Переименовать" onclick="ChatList.startRename(event, '${chat.id}')">✏️</button>
                <button class="chat-action-btn delete" title="Удалить" onclick="ChatList.deleteChat(event, '${chat.id}')">🗑️</button>
            </div>`;
        item.addEventListener('click', (e) => {
            // BUG-12 FIX: Prevent rapid double-clicks
            if (Chat._openingChat) return;
            Chat._openingChat = true;
            Chat.open(chat.id).finally(() => { Chat._openingChat = false; });
        });
        return item;
    },

    filter(query) {
        const q = query.toLowerCase().trim();
        if (!q) { this.render(); return; }
        const filtered = state.chats.filter(c => (c.title || '').toLowerCase().includes(q));
        this.render(filtered);
    },

    setActive(chatId) {
        $$('.chat-item').forEach(el => el.classList.toggle('active', el.dataset.chatId === String(chatId)));
    },

    startRename(e, chatId) {
        e.stopPropagation();
        const item = document.querySelector(`.chat-item[data-chat-id="${chatId}"]`);
        if (!item) return;
        const titleEl = item.querySelector('.chat-item-title');
        const currentTitle = titleEl.textContent;
        const input = el('input', 'chat-item-rename-input');
        input.value = currentTitle;
        titleEl.replaceWith(input);
        input.focus();
        input.select();
        const finish = async () => {
            const newTitle = input.value.trim() || currentTitle;
            const span = el('div', 'chat-item-title', Utils.escapeHtml(newTitle));
            input.replaceWith(span);
            if (newTitle !== currentTitle) {
                await Chat.renameChat(chatId, newTitle);
            }
        };
        input.addEventListener('blur', finish);
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') input.blur();
            if (e.key === 'Escape') { input.value = currentTitle; input.blur(); }
        });
    },

    async deleteChat(e, chatId) {
        e.stopPropagation();
        e.preventDefault();
        if (!confirm('Удалить чат? Это необратимо.')) return;
        try {
            await API.delete('/chats/' + chatId);
            state.chats = state.chats.filter(c => c.id !== chatId);
            if (state.currentChatId === chatId) {
                state.currentChatId = null;
                UI.renderWelcome();
                UI.updateChatTitle('');
            }
            this.render();
            Toast.show('Чат удалён', 'success');
        } catch (err) {
            Toast.show('Ошибка удаления: ' + err.message, 'error');
        }
    },

    updateChatCost(chatId, cost) {
        const item = document.querySelector(`.chat-item[data-chat-id="${chatId}"]`);
        if (item) {
            const costEl = item.querySelector('.chat-item-cost');
            if (costEl) costEl.textContent = Utils.formatCost(cost);
        }
        const chat = state.chats.find(c => c.id === chatId);
        if (chat) chat.total_cost = cost;
    }
};

/* ── CHAT ─────────────────────────────────────────────────── */

// ── ПАТЧ B1: Tool Action Chips ──────────────────────────────────────
function addToolChip(parentEl, toolName, args) {
    if (!parentEl) return null;
    const chip = document.createElement('div');
    chip.className = 'tool-chip';
    const emojis = {
        'ssh_execute': '🔧', 'file_write': '📝', 'file_read': '📖',
        'browser_navigate': '🌐', 'browser_screenshot': '📸',
        'create_artifact': '🎨', 'generate_file': '📄',
        'web_search': '🔍', 'code_interpreter': '💻',
        'generate_chart': '📊', 'generate_image': '🎨',
    };
    const emoji = emojis[toolName] || '⚡';
    const labels = {
        'ssh_execute': 'Выполняю на сервере',
        'file_write': 'Создаю файл',
        'file_read': 'Читаю файл',
        'browser_navigate': 'Открываю страницу',
        'browser_screenshot': 'Делаю скриншот',
        'create_artifact': 'Создаю дизайн',
        'generate_file': 'Генерирую документ',
        'web_search': 'Ищу в интернете',
        'code_interpreter': 'Выполняю код',
    };
    const label = labels[toolName] || toolName;
    const shortArgs = typeof args === 'string' ? args.substring(0, 60) : (args ? JSON.stringify(args).substring(0, 60) : '');
    chip.innerHTML = '<span class="tool-chip-emoji">' + emoji + '</span>' +
        '<span class="tool-chip-label">' + label + '</span>' +
        (shortArgs ? '<span class="tool-chip-args">' + shortArgs + '</span>' : '') +
        '<span class="tool-chip-spinner"></span>';
    chip.dataset.toolId = Date.now();
    parentEl.appendChild(chip);
    return chip;
}

function completeToolChip(chip, success) {
    if (!chip) return;
    chip.classList.add(success ? 'done' : 'error');
    const spinner = chip.querySelector('.tool-chip-spinner');
    if (spinner) spinner.textContent = success ? '✅' : '❌';
}
// ── КОНЕЦ ПАТЧ B1 ────────────────────────────────────────────────────


// ── ПАТЧ B1: Tool Action Chips ──────────────────────────────────────
function addToolChip(parentEl, toolName, args) {
    if (!parentEl) return null;
    const chip = document.createElement('div');
    chip.className = 'tool-chip';
    const emojis = {
        'ssh_execute': '🔧', 'file_write': '📝', 'file_read': '📖',
        'browser_navigate': '🌐', 'browser_screenshot': '📸',
        'create_artifact': '🎨', 'generate_file': '📄',
        'web_search': '🔍', 'code_interpreter': '💻',
        'generate_chart': '📊', 'generate_image': '🎨',
    };
    const emoji = emojis[toolName] || '⚡';
    const labels = {
        'ssh_execute': 'Выполняю на сервере',
        'file_write': 'Создаю файл',
        'file_read': 'Читаю файл',
        'browser_navigate': 'Открываю страницу',
        'browser_screenshot': 'Делаю скриншот',
        'create_artifact': 'Создаю дизайн',
        'generate_file': 'Генерирую документ',
        'web_search': 'Ищу в интернете',
        'code_interpreter': 'Выполняю код',
    };
    const label = labels[toolName] || toolName;
    const shortArgs = typeof args === 'string' ? args.substring(0, 60) : (args ? JSON.stringify(args).substring(0, 60) : '');
    chip.innerHTML = '<span class="tool-chip-emoji">' + emoji + '</span>' +
        '<span class="tool-chip-label">' + label + '</span>' +
        (shortArgs ? '<span class="tool-chip-args">' + shortArgs + '</span>' : '') +
        '<span class="tool-chip-spinner"></span>';
    chip.dataset.toolId = Date.now();
    parentEl.appendChild(chip);
    return chip;
}

function completeToolChip(chip, success) {
    if (!chip) return;
    chip.classList.add(success ? 'done' : 'error');
    const spinner = chip.querySelector('.tool-chip-spinner');
    if (spinner) spinner.textContent = success ? '✅' : '❌';
}
// ── КОНЕЦ ПАТЧ B1 ────────────────────────────────────────────────────

const Chat = {
    async newChat() {
        if (state.isStreaming) Chat.stop();
        state.currentChatId = null;
        state.messages = [];
        state.attachments = [];
        state.currentChatCost = 0;
        Attachments.renderPreviews();
        UI.renderWelcome();
        UI.updateChatTitle('Новый чат');
        ChatList.setActive(null);
        ActivityPanel.clear();
        ActivityPanel.hide();
        const textarea = $('message-input');
        if (textarea) { textarea.value = ''; UI.autoResize(textarea); textarea.focus(); }
        Sidebar.close();
    },

    async open(chatId) {
        if (state.isStreaming) Chat.stop();
        // BUG-12 FIX: Save previous state in case of error
        const prevChatId = state.currentChatId;
        const prevMessages = [...state.messages];
        state.currentChatId = chatId;
        state.messages = [];
        ChatList.setActive(chatId);
        ActivityPanel.clear();
        Sidebar.close();

        const chat = state.chats.find(c => c.id === chatId);
        UI.updateChatTitle(chat?.title || 'Чат');
        // FIX КРИТ-2: Восстанавливаем currentChatCost из данных чата при открытии
        state.currentChatCost = chat?.total_cost || 0;
        UI.updateFooterInfo();

        // Restore draft from sessionStorage
        const textarea = $('message-input');
        if (textarea) {
            const draft = sessionStorage.getItem('draft_' + chatId);
            if (draft) {
                textarea.value = draft;
                UI.autoResize(textarea);
            } else {
                textarea.value = '';
            }
        }

        try {
            const data = await API.get('/chats/' + chatId);
            // Backend returns {chat: {messages: [...], ...}}
            const chatData = data.chat || data;
            state.messages = chatData.messages || data.messages || [];
            // FIX КРИТ-2: Обновляем currentChatCost из свежих данных чата
            if (chatData.total_cost !== undefined) {
                state.currentChatCost = chatData.total_cost || 0;
                UI.updateFooterInfo();
            }
            this.renderMessages();

            // ══ TASK PERSISTENCE: check if a task is running for this chat ══
            this._checkRunningTask(chatId);

        } catch (e) {
            // BUG-12 FIX: Restore previous state on error instead of leaving empty
            console.warn('Chat.open error:', e);
            if (e.message === 'Unauthorized') {
                // Token expired — don't restore, logout already happened
                return;
            }
            state.currentChatId = prevChatId;
            state.messages = prevMessages;
            ChatList.setActive(prevChatId);
            if (prevMessages.length) this.renderMessages();
            Toast.show('Ошибка загрузки чата: ' + e.message, 'error');
        }
    },

    renderMessages() {
        const container = $('messages-container');
        if (!container) return;
        container.innerHTML = '';
        if (!state.messages.length) {
            UI.renderWelcome();
            return;
        }
        state.messages.forEach(msg => {
            const el = Messages.render(msg);
            if (el) container.appendChild(el);
        });
        this.scrollToBottom();
    },

    scrollToBottom(smooth = true) {
        const wrap = $('messages-wrap');
        if (wrap) {
            wrap.scrollTo({ top: wrap.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
        }
    },

    smartScroll() {
        const wrap = $('messages-wrap');
        if (!wrap) return;
        const isAtBottom = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 100;
        if (isAtBottom) {
            wrap.scrollTop = wrap.scrollHeight;
        }
    },

    async send() {
        const textarea = $('message-input');
        if (!textarea) return;
        const text = textarea.value.trim();
        if (!text && !state.attachments.length) return;

        if (state.isStreaming) {
            // Priority detection: "сейчас", "срочно", "now", "urgent" → push to front
            const _urgentKw = ['сейчас', 'срочно', 'now', 'urgent', 'немедленно'];
            const _isUrgent = _urgentKw.some(kw => text.toLowerCase().includes(kw));
            const queueItem = { text, attachments: [...state.attachments], priority: _isUrgent };
            if (_isUrgent) {
                state.messageQueue.unshift(queueItem);
                Toast.show('⚡ Срочная задача добавлена в начало очереди', 'info');
            } else {
                state.messageQueue.push(queueItem);
            }
            UI.showQueueIndicator(state.messageQueue.length);
            // Clear draft on queue
            sessionStorage.removeItem('draft_' + state.currentChatId);
            textarea.value = '';
            UI.autoResize(textarea);
            state.attachments = [];
            Attachments.renderPreviews();
            return;
        }

        textarea.value = '';
        UI.autoResize(textarea);
        const attachments = [...state.attachments];
        state.attachments = [];
        Attachments.renderPreviews();
        // Clear draft on send
        if (state.currentChatId) sessionStorage.removeItem('draft_' + state.currentChatId);

        await this._doSend(text, attachments);
    },

    async _doSend(text, attachments = []) {
        if (!state.currentChatId) {
            try {
                const chatRaw = await API.post('/chats', { title: text.slice(0, 50) || 'Новый чат', mode: state.mode });
                const chat = chatRaw.chat || chatRaw;
                state.currentChatId = chat.id;
                state.chats.unshift(chat);
                ChatList.render();
                ChatList.setActive(chat.id);
                UI.updateChatTitle(chat.title);
            } catch (e) {
                Toast.show('Ошибка создания чата: ' + e.message, 'error');
                return;
            }
        }

        // Remove welcome screen
        const ws = document.querySelector('.welcome-screen');
        if (ws) ws.remove();

        // Add user message
        const userMsg = { id: Utils.generateId(), role: 'user', content: text, attachments, created_at: new Date().toISOString() };
        state.messages.push(userMsg);
        const userEl = Messages.render(userMsg);
        if (userEl) $('messages-container').appendChild(userEl);
        this.scrollToBottom();

        // Start streaming
        UI.setStreaming(true);
        ActivityPanel.show();
        ActivityPanel.setStatus('running');

        const startTime = Date.now();
        let aiMsgEl = null;
        let aiContent = '';
        let aiMsgId = Utils.generateId();

        // Add AI message placeholder
        const aiMsg = { id: aiMsgId, role: 'assistant', content: '', created_at: new Date().toISOString() };
        aiMsgEl = Messages.renderStreaming(aiMsg);
        $('messages-container').appendChild(aiMsgEl);
        this.scrollToBottom();

        try {
            const body = {
                message: text,
                mode: state.mode,
                attachments: attachments.map(a => a.id || a.url).filter(Boolean),
                verify: document.getElementById('verification-toggle')?.checked || false
            };
            // Multi-SSH: отправляем SSH данные активного сервера
            if (typeof MultiSSH !== 'undefined') {
                body.ssh = MultiSSH.getCredentials();
            }

            const controller = new AbortController();
            state.streamController = controller;

            const res = await fetch(API_BASE + '/chats/' + state.currentChatId + '/send', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + state.token
                },
                body: JSON.stringify(body),
                signal: controller.signal
            });

            if (!res.ok) throw new Error('Stream error ' + res.status);

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const raw = line.slice(6).trim();
                        if (raw === '[DONE]') break;
                        try {
                            const evt = JSON.parse(raw);
                            aiContent = this._handleSSE(evt, aiMsgEl, aiContent, startTime);
                        } catch (e) {
                            // plain text chunk
                            aiContent += raw;
                            Messages.updateStreamContent(aiMsgEl, aiContent);
                        }
                        this.scrollToBottom(false);
                    }
                }
            }
        } catch (err) {
            if (err.name !== 'AbortError') {
                ActivityPanel.addLine('error', '❌', 'Ошибка: ' + err.message);
                Toast.show('Ошибка: ' + err.message, 'error');
            }
        } finally {
            const duration = Date.now() - startTime;
            Messages.finalizeStreaming(aiMsgEl, aiContent, duration);
            state.isStreaming = false;
            state.streamController = null;
            UI.setStreaming(false);
            ActivityPanel.setStatus('done');

            // Auto-generate title after first message
            if (state.currentChatId && text) {
                const chat = state.chats.find(c => c.id === state.currentChatId);
                const msgCount = state.messages.filter(m => m.role === 'user').length;
                if (chat && (chat.title === 'Новый чат' || chat.title === text.slice(0, 50)) && msgCount <= 1) {
                    setTimeout(() => Chat.autoGenerateTitle(state.currentChatId, text), 500);
                }
            }

            // Process queue
            if (state.messageQueue.length > 0) {
                const next = state.messageQueue.shift();
                UI.showQueueIndicator(state.messageQueue.length);
                setTimeout(() => this._doSend(next.text, next.attachments), 300);
            }
        }
    },

    _handleSSE(evt, aiMsgEl, aiContent, startTime) {
        // ПАТЧ 8: Обработка событий верификации
        if (evt.type === 'verification') {
            const status = evt.status;
            let verifyText = '';
            if (status === 'checking') {
                verifyText = `Проверяю результат через ${evt.model || 'второй ИИ'}...`;
            } else if (status === 'verified') {
                verifyText = `Проверено — ошибок нет`;
            } else if (status === 'issues_found') {
                verifyText = `Найдено проблем: ${evt.issues}. ${evt.details || ''}`;
            } else if (status === 'ok') {
                verifyText = `${evt.message || 'Проверка пройдена'}`;
            } else if (status === 'warning') {
                verifyText = `${evt.message || 'Возможная проблема'}`;
            }
            if (verifyText) {
                const actPanel = document.querySelector('.activity-panel, .actions-log');
                if (actPanel) {
                    const div = document.createElement('div');
                    div.className = 'activity-item verification';
                    div.textContent = verifyText;
                    div.style.cssText = 'padding: 4px 8px; font-size: 12px; color: #7c5cfc; border-left: 2px solid #7c5cfc;';
                    actPanel.appendChild(div);
                }
            }
            return aiContent;
        }
        switch (evt.type) {
            case 'content':  // backend sends {type: 'content', text: '...'}
            case 'text':
            case 'delta':
                // ПАТЧ B3: убираем индикатор "Думаю..." когда начинает приходить текст
                {
                    const _thinkEl = aiMsgEl ? aiMsgEl.querySelector('.thinking-indicator') : null;
                    if (_thinkEl) _thinkEl.remove();
                    state._thinkingShown = false;
                }
                aiContent += evt.text || evt.content || evt.delta || '';
                Messages.updateStreamContent(aiMsgEl, aiContent);
                Chat.smartScroll();  // УЛУЧ-1: автоскролл при каждом чанке
                break;
            case 'done':  // backend sends {type: 'done', cost: X, tokens_in: X, tokens_out: X}
                {
                    // КРИТ-2 FIX: parseFloat гарантирует число даже если cost пришёл строкой
                    const doneCost = parseFloat(evt.cost) || 0;
                    if (doneCost > 0) {
                        state.totalCost = (state.totalCost || 0) + doneCost;
                        state.currentChatCost = (state.currentChatCost || 0) + doneCost;
                    }
                    UI.updateCostBar();
                    UI.updateFooterInfo();
                    if (state.currentChatId && doneCost > 0) {
                        const chat = state.chats.find(c => c.id === state.currentChatId);
                        if (chat) {
                            chat.total_cost = (chat.total_cost || 0) + doneCost;
                            ChatList.updateChatCost(state.currentChatId, chat.total_cost);
                        }
                    }
                    // УЛУЧ-2: метаданные под ответом AI
                    if (aiMsgEl) {
                        const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                        const metaDiv = document.createElement('div');
                        metaDiv.className = 'msg-meta msg-meta-stream';
                        const modelName = evt.model || 'DeepSeek V3';
                        const costStr = doneCost > 0 ? '$' + doneCost.toFixed(3) : '';
                        const tokensOut = evt.tokens_out || evt.tokens || 0;
                        const parts = [modelName, costStr, elapsed + 'с'];
                        if (tokensOut > 0) parts.push(tokensOut + ' токенов');
                        metaDiv.textContent = parts.filter(Boolean).join(' · ');
                        const msgWrapper = aiMsgEl.closest('.message') || aiMsgEl.parentElement;
                        if (msgWrapper) msgWrapper.appendChild(metaDiv);
                    }
                }
                break;
            case 'meta':  // backend sends metadata at start, ignore
                break;

            // ── BUG-4 FIX: thinking ──────────────────────────────────
            case 'model_info':
            case 'agent_mode':
                {
                    const modelEl = document.querySelector('.header-model, .model-label, [data-model]');
                    if (modelEl && evt.model) {
                        const labels = {
                            'deepseek/deepseek-v3.2': 'DeepSeek V3',
                            'google/gemini-2.5-pro': 'Gemini Pro',
                            'anthropic/claude-sonnet-4.6': 'Claude Sonnet',
                            'anthropic/claude-opus-4': 'Claude Opus'
                        };
                        modelEl.textContent = labels[evt.model] || evt.model;
                    }
                }
                break;
            case 'thinking':
                ActivityPanel.show();
                ActivityPanel.setStatus('running');
                ActivityPanel.addLine('thinking', '🤔', evt.content || evt.text || '');
                // EXTENDED THINKING: показываем блок размышлений в чате
                {
                    const _thinkBubble = aiMsgEl ? aiMsgEl.querySelector('.msg-bubble') : null;
                    if (_thinkBubble) {
                        // Убираем индикатор загрузки если есть
                        const _oldIndicator = _thinkBubble.querySelector('.thinking-indicator');
                        if (_oldIndicator) _oldIndicator.remove();
                        // Создаём или обновляем thinking-block
                        let _thinkBlock = _thinkBubble.querySelector('.thinking-block');
                        if (!_thinkBlock) {
                            _thinkBlock = document.createElement('div');
                            _thinkBlock.className = 'thinking-block';
                            _thinkBlock.innerHTML = '<div class="thinking-header">🧠 Анализирую задачу...</div><div class="thinking-content"></div>';
                            _thinkBubble.appendChild(_thinkBlock);
                        }
                        const _thinkContent = _thinkBlock.querySelector('.thinking-content');
                        if (_thinkContent) {
                            const thinkText = evt.content || evt.text || '';
                            _thinkContent.innerHTML = (typeof marked !== 'undefined' ? marked.parse(thinkText) : thinkText.replace(/\n/g, '<br>'));
                        }
                        state._thinkingShown = true;
                    }
                }
                break;

            // ── BUG-4 FIX: tool_start / tool ─────────────────────────
            case 'tool':
            case 'tool_start':
                ActivityPanel.show();
                ActivityPanel.setStatus('running');
                ActivityPanel.addLine('tool-start', this._toolEmoji(evt.tool || evt.name), (evt.tool || evt.name || 'tool') + ': ' + (evt.args ? JSON.stringify(evt.args).substring(0, 100) : ''));
                // ПАТЧ B1: добавляем плашку в чат
                {
                    const _bubble = aiMsgEl ? aiMsgEl.querySelector('.msg-bubble') : null;
                    if (_bubble) {
                        state._lastToolChip = addToolChip(_bubble, evt.tool || evt.name || 'tool', evt.args || '');
                    }
                }
                // ПАТЧ W2-2: Автоматически продвигать task progress
                if (state.taskProgress && state.taskProgress.steps && state.taskProgress.steps.length) {
                    const pendingIdx = state.taskProgress.steps.findIndex(s => s.status === 'pending');
                    if (pendingIdx >= 0) {
                        state.taskProgress.steps.forEach(s => { if (s.status === 'running') s.status = 'done'; });
                        state.taskProgress.steps[pendingIdx].status = 'running';
                        state.taskProgress.current = state.taskProgress.steps.filter(s => s.status === 'done').length;
                        ActivityPanel.renderTaskProgress();
                    }
                }
                break;

            // ── BUG-4 FIX: tool_result — backend sends evt.preview, not evt.result ──
            case 'tool_result':
                {
                    // ПАТЧ B1: завершаем плашку
                    if (state._lastToolChip) {
                        const _isErr = evt.error || (evt.success === false);
                        completeToolChip(state._lastToolChip, !_isErr);
                        state._lastToolChip = null;
                    }
                    // ПАТЧ B1: завершаем плашку
                    if (state._lastToolChip) {
                        const _isErr = evt.error || (evt.success === false);
                        completeToolChip(state._lastToolChip, !_isErr);
                        state._lastToolChip = null;
                    }
                    // Download button for file results
                    if (evt.file_path || evt.download_url || evt.file_id) {
                        const dlUrl = evt.download_url || evt.file_path || ('/api/files/' + evt.file_id + '/download');
                        const dlName = evt.filename || dlUrl.split('/').pop() || 'file';
                        const downloadBtn = document.createElement('a');
                        downloadBtn.href = dlUrl;
                        downloadBtn.download = dlName;
                        downloadBtn.className = 'file-download-btn';
                        downloadBtn.innerHTML = '📥 Скачать ' + dlName;
                        const msgContainer = document.querySelector('#messages-container .message.ai:last-child .msg-bubble');
                        if (msgContainer) msgContainer.appendChild(downloadBtn);
                    }
                    // BUG-4 FIX: backend sends 'preview' field, also check result/output/summary/text
                    const resultText = evt.preview || evt.summary || evt.result || evt.output || evt.text || '';
                    const isError = evt.error || (evt.success === false);
                    ActivityPanel.addLine(
                        isError ? 'error' : 'tool-result',
                        isError ? '❌' : '📄',
                        resultText.substring(0, 300),
                        true
                    );
                    // Screenshot from browser tools
                    if (evt.screenshot) {
                        ActivityPanel.addScreenshot(evt.url || '', evt.screenshot, evt.status || '');
                    }
                }
                break;

            case 'code_write':
                ActivityPanel.addCodeBlock(evt.filename || 'file', evt.content || '');
                break;

            case 'browser_update':
                ActivityPanel.addScreenshot(evt.url || '', evt.screenshot || '', evt.status || '');
                break;

            // ── BUG-4 FIX: agent_iteration — backend sends this, not 'iteration' ──
            case 'agent_iteration':
                ActivityPanel.show();
                ActivityPanel.setStatus('running');
                ActivityPanel.updateProgress(evt.iteration || evt.current, evt.max || evt.total, evt.steps || []);
                ActivityPanel.addLine('iteration', '🔄', `Итерация ${evt.iteration || evt.current || '?'} / ${evt.max || evt.total || '?'}`);
                break;

            case 'iteration':
                ActivityPanel.updateProgress(evt.current, evt.total, evt.steps);
                ActivityPanel.addLine('iteration', '🔄', `Итерация ${evt.current}/${evt.total}`);
                break;

            // ── BUG-4 FIX: self_heal — показываем в панели ───────────
            case 'self_heal':
                ActivityPanel.addLine('thinking', '🔁', `Самоисправление #${evt.attempt || 1}: ${evt.fix_description || 'применяю фикс...'}`);
                break;

            case 'chart':
            case 'generate_chart': {
                const chartId = 'chart-' + Date.now();
                const wrap = document.createElement('div');
                wrap.className = 'chart-artifact';
                wrap.innerHTML = `
                    <div class="artifact-header">
                        <span>📊 ${evt.title || 'График'}</span>
                        <button class="art-btn" onclick="this.closest('.chart-artifact').querySelector('canvas').toBlob(b=>{const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='chart.png';a.click()})">📥 Скачать</button>
                    </div>
                    <div class="chart-container"><canvas id="${chartId}" height="300"></canvas></div>
                `;
                const body = aiMsgEl ? aiMsgEl.querySelector('.msg-body') : null;
                if (body) body.appendChild(wrap);
                setTimeout(() => {
                    const ctx = document.getElementById(chartId);
                    if (ctx && typeof Chart !== 'undefined') {
                        new Chart(ctx, evt.config || {
                            type: evt.chart_type || 'bar',
                            data: evt.data || {},
                            options: { responsive: true, maintainAspectRatio: false, 
                                       plugins: { legend: { position: 'bottom' } } }
                        });
                    }
                }, 100);
                break;
            }
            case 'artifact':
                Messages.addArtifact(aiMsgEl, evt);
                break;

            case 'artifact_update': {
                const artId = evt.artifact_id || Date.now();
                ArtifactManager.create(artId, evt.html_content, evt.artifact_type, evt.filename);
                break;
            }
            case 'followups':
                Messages.addFollowups(aiMsgEl, evt.suggestions || []);
                break;
            case 'task_steps':
                // ПАТЧ W1-2 + W2-2: Показать план в Activity Panel
                ActivityPanel.show();
                if (evt.steps && evt.steps.length) {
                    state.taskProgress = {
                        current: 0,
                        total: evt.steps.length,
                        steps: evt.steps.map((s, i) => ({
                            name: s.name || s,
                            status: 'pending',
                            index: i
                        }))
                    };
                    ActivityPanel.renderTaskProgress();
                }
                break;
            case 'step_update':
                // ПАТЧ W2-2: Обновление конкретного шага
                if (state.taskProgress && state.taskProgress.steps && evt.step_index != null) {
                    state.taskProgress.steps[evt.step_index].status = evt.status || 'done';
                    state.taskProgress.current = state.taskProgress.steps.filter(s => s.status === 'done').length;
                    ActivityPanel.renderTaskProgress();
                }
                break;
            case 'task_complete':
                Messages.addTaskSummary(aiMsgEl, evt);
                // Push notification
                if ('Notification' in window && Notification.permission === 'granted') {
                    new Notification('ORION Digital', {
                        body: '✅ Задача завершена: ' + (evt.summary || 'готово'),
                        icon: '/favicon.ico'
                    });
                }
                // ПАТЧ W2-2: Все шаги done
                if (state.taskProgress && state.taskProgress.steps) {
                    state.taskProgress.steps.forEach(s => { if (s.status !== 'error') s.status = 'done'; });
                    state.taskProgress.current = state.taskProgress.total;
                    ActivityPanel.renderTaskProgress();
                }
                ActivityPanel.setStatus('done');
                break;
            case 'human_handoff':
                ActivityPanel.showTakeover(evt.message || 'Агент нуждается в помощи', evt.screenshot || '');
                break;
            case 'task_plan':
                // Оркестратор прислал план выполнения задачи
                TaskPlan.show(evt);
                break;
            case 'phase_start':
                TaskPlan.startPhase(evt.phase_index, evt.phase_name, evt.agents);
                break;
            case 'phase_complete':
                TaskPlan.completePhase(evt.phase_index, evt.success);
                break;
            case 'ask_user':
                // Агент спрашивает пользователя
                AskUser.show(evt.question);
                break;

            case 'auth_required':
                // ПАТЧ ЗАДАЧА-1: browser_ask_auth — безопасная авторизация
                AuthForm.show(evt);
                break;

            case 'thinking_start':
                ActivityPanel.addLine('thinking', '🧠', 'Анализирую задачу...');
                break;
            case 'thinking_end': {
                const blocks = document.querySelectorAll('.thinking-block');
                if (blocks.length) {
                    const last = blocks[blocks.length - 1];
                    last.classList.add('thinking-collapsed');
                    last.querySelector('.thinking-header').onclick = () => last.classList.toggle('thinking-collapsed');
                }
                break;
            }
            case 'error':
                ActivityPanel.addLine('error', '❌', evt.message || evt.error || 'Ошибка');
                break;
            case 'cost':
                {
                    const costVal = evt.cost || evt.amount || 0;
                    // FIX КРИТ-2: накапливаем стоимость в state
                    state.totalCost += costVal;
                    state.currentChatCost = (state.currentChatCost || 0) + costVal;
                    UI.updateCostBar();
                    UI.updateFooterInfo();
                    if (state.currentChatId) {
                        const chatObj = state.chats.find(c => c.id === state.currentChatId);
                        if (chatObj) {
                            chatObj.total_cost = (chatObj.total_cost || 0) + costVal;
                            ChatList.updateChatCost(state.currentChatId, chatObj.total_cost);
                        }
                    }
                }
                break;
            case 'title':
                if (evt.title) {
                    UI.updateChatTitle(evt.title);
                    const chat = state.chats.find(c => c.id === state.currentChatId);
                    if (chat) { chat.title = evt.title; ChatList.render(); }
                }
                break;
        }
        return aiContent;
    },

    _toolEmoji(tool) {
        const map = {
            ssh_execute: '🔧', file_write: '📝', file_read: '📖',
            browser_navigate: '🌐', browser_get_text: '🌐', browser_check_site: '🌐',
            browser_check_api: '🌐', browser_click: '👆', browser_fill: '✍️',
            browser_submit: '📨', browser_select: '📋', browser_ask_auth: '🔐',
            ftp_upload: '📤', ftp_download: '📥', ftp_list: '📂',
            web_search: '🔍', web_fetch: '🔍',
            code_interpreter: '💻', generate_file: '📄', generate_image: '🖼️',
            generate_chart: '📊', generate_report: '📋', create_artifact: '🎨',
            store_memory: '🧠', recall_memory: '🧠', analyze_image: '🔍',
            read_any_file: '📖', edit_image: '🖼️', generate_design: '🎨'
        };
        return map[tool] || '🔧';
    },

    stop() {
        if (state.streamController) {
            state.streamController.abort();
            state.streamController = null;
        }
        state.isStreaming = false;
        state.messageQueue = [];
        UI.setStreaming(false);
        UI.showQueueIndicator(0);
        ActivityPanel.setStatus('done');
        Toast.show('Остановлено', 'warning');
    },

    removeFromQueue(index) {
        if (index >= 0 && index < state.messageQueue.length) {
            const removed = state.messageQueue.splice(index, 1)[0];
            UI.showQueueIndicator(state.messageQueue.length);
            Toast.show('Задача удалена: ' + (removed.text || '').slice(0, 30), 'info');
        }
    },

    // ══ TASK PERSISTENCE: check if backend has a running task for this chat ══
    async _checkRunningTask(chatId) {
        try {
            const status = await API.get('/chats/' + chatId + '/status');
            if (status.status === 'running') {
                console.log('[TaskPersist] Running task found for chat', chatId, '- reconnecting...');
                Toast.show('⚡ Переподключение к задаче...', 'info');
                this._reconnectSSE(chatId);
            }
        } catch (e) {
            // No running task or endpoint not available — that's fine
            console.log('[TaskPersist] No running task for', chatId);
        }
    },

    // ══ TASK PERSISTENCE: reconnect to running task SSE stream ══
    async _reconnectSSE(chatId) {
        UI.setStreaming(true);
        ActivityPanel.show();
        ActivityPanel.setStatus('running');
        ActivityPanel.addLine('info', '🔄', 'Переподключение к задаче...');

        const startTime = Date.now();
        let aiMsgEl = null;
        let aiContent = '';

        // Create AI message placeholder for reconnected stream
        const aiMsg = { id: Utils.generateId(), role: 'assistant', content: '', created_at: new Date().toISOString() };
        aiMsgEl = Messages.renderStreaming(aiMsg);
        $('messages-container').appendChild(aiMsgEl);
        this.scrollToBottom();

        try {
            const controller = new AbortController();
            state.streamController = controller;
            state.isStreaming = true;

            const res = await fetch(API_BASE + '/chats/' + chatId + '/reconnect', {
                method: 'GET',
                headers: { 'Authorization': 'Bearer ' + state.token },
                signal: controller.signal
            });

            if (!res.ok) throw new Error('Reconnect error ' + res.status);

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const raw = line.slice(6).trim();
                        if (raw === '[DONE]') break;
                        try {
                            const evt = JSON.parse(raw);
                            aiContent = this._handleSSE(evt, aiMsgEl, aiContent, startTime);
                        } catch (e) {
                            aiContent += raw;
                            Messages.updateStreamContent(aiMsgEl, aiContent);
                        }
                        this.scrollToBottom(false);
                    }
                }
            }
        } catch (err) {
            if (err.name !== 'AbortError') {
                ActivityPanel.addLine('error', '❌', 'Ошибка переподключения: ' + err.message);
            }
        } finally {
            const duration = Date.now() - startTime;
            Messages.finalizeStreaming(aiMsgEl, aiContent, duration);
            state.isStreaming = false;
            state.streamController = null;
            UI.setStreaming(false);
            ActivityPanel.setStatus('done');

            // Process queue after reconnected task finishes
            if (state.messageQueue.length > 0) {
                const next = state.messageQueue.shift();
                UI.showQueueIndicator(state.messageQueue.length);
                setTimeout(() => this._doSend(next.text, next.attachments), 300);
            }
        }
    },

    regenerate() {
        // BUG-14 FIX: Regenerate last AI response
        const lastUserMsg = [...state.messages].reverse().find(m => m.role === 'user');
        if (!lastUserMsg) return;
        // Remove last AI message from DOM
        const msgs = document.querySelectorAll('#messages-container .message.ai');
        if (msgs.length) msgs[msgs.length - 1].remove();
        // Remove last AI message from state
        const lastAiIdx = [...state.messages].reverse().findIndex(m => m.role === 'assistant');
        if (lastAiIdx !== -1) state.messages.splice(state.messages.length - 1 - lastAiIdx, 1);
        // Resend
        this._doSend(lastUserMsg.content, []);
    },

    sendFromChip(text) {
        const textarea = $('message-input');
        if (textarea) {
            textarea.value = text;
            UI.autoResize(textarea);
        }
        this.send();
    },

    async renameCurrentChat(title) {
        if (!state.currentChatId || !title.trim()) return;
        const chat = state.chats.find(c => c.id === state.currentChatId);
        if (chat && chat.title === title.trim()) return;
        await this.renameChat(state.currentChatId, title.trim());
    },

    async renameChat(chatId, title) {
        try {
            await API.put('/chats/' + chatId + '/rename', { title });
            const chat = state.chats.find(c => c.id === chatId);
            if (chat) chat.title = title;
            ChatList.render();
        } catch (e) {
            console.warn('Rename error:', e);
        }
    },

    async autoGenerateTitle(chatId, userMessage) {
        try {
            const res = await fetch(API_BASE + '/chat/quick', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + state.token },
                body: JSON.stringify({
                    message: 'Придумай короткое название (3-5 слов) для чата где пользователь спросил: "' + userMessage.substring(0, 100) + '". Ответь ТОЛЬКО названием, без кавычек и пояснений.',
                    model: 'deepseek/deepseek-v3.2'
                })
            });
            const data = await res.json();
            const title = (data.response || data.text || data.content || '').trim().substring(0, 50);
            if (title && title.length > 2) {
                await this.renameChat(chatId, title);
                const titleEl = document.querySelector('.chat-title') || document.getElementById('chat-title');
                if (titleEl) titleEl.textContent = title;
            }
        } catch (e) { console.warn('Auto title failed:', e); }
    }
};

/* ── MESSAGES ─────────────────────────────────────────────── */
const Messages = {
    render(msg) {
        const isUser = msg.role === 'user';
        const wrapper = el('div', 'message ' + (isUser ? 'user' : 'ai'));
        wrapper.dataset.msgId = msg.id;

        const avatar = el('div', 'msg-avatar', isUser ? (state.user?.username?.[0]?.toUpperCase() || 'U') : '🤖');
        const body = el('div', 'msg-body');
        const bubble = el('div', 'msg-bubble' + (isUser ? '' : ' msg-ai'));

        if (isUser) {
            bubble.textContent = msg.content;
            if (msg.attachments?.length) {
                const attWrap = el('div', 'msg-attachments');
                msg.attachments.forEach(a => {
                    const att = el('div', 'msg-attachment-item', Utils.escapeHtml(a.name || a));
                    attWrap.appendChild(att);
                });
                bubble.appendChild(attWrap);
            }
        } else {
            bubble.innerHTML = this.renderMarkdown(msg.content);
            this.highlightCode(bubble);
            this.addCopyButtons(bubble);
        this.enhanceHtmlBlocks(bubble);
            if (msg.meta) {
                body.appendChild(bubble);
                body.appendChild(this.renderMeta(msg.meta));
                body.appendChild(this.renderActions(msg.content));
                wrapper.appendChild(avatar);
                wrapper.appendChild(body);
                return wrapper;
            }
        }

        body.appendChild(bubble);
        if (!isUser) {
            body.appendChild(this.renderActions(msg.content));
        }
        wrapper.appendChild(avatar);
        wrapper.appendChild(body);
        return wrapper;
    },

    renderStreaming(msg) {
        const wrapper = el('div', 'message ai');
        wrapper.dataset.msgId = msg.id;
        const avatar = el('div', 'msg-avatar', '🤖');
        const body = el('div', 'msg-body');
        const bubble = el('div', 'msg-bubble msg-ai');
        bubble.innerHTML = '<span class="typing-indicator"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></span>';
        body.appendChild(bubble);
        wrapper.appendChild(avatar);
        wrapper.appendChild(body);
        return wrapper;
    },

    updateStreamContent(wrapper, content) {
        const bubble = wrapper.querySelector('.msg-bubble');
        if (!bubble) return;
        bubble.innerHTML = this.renderMarkdown(content) + '<span class="stream-cursor"></span>';
        this.highlightCode(bubble);
    },

    finalizeStreaming(wrapper, content, duration) {
        const bubble = wrapper.querySelector('.msg-bubble');
        if (!bubble) return;
        bubble.innerHTML = this.renderMarkdown(content);
        this.highlightCode(bubble);
        this.addCopyButtons(bubble);
        this.enhanceHtmlBlocks(bubble);
        const body = wrapper.querySelector('.msg-body');
        if (body) {
            body.appendChild(this.renderActions(content));
        }
    },

    enhanceHtmlBlocks(messageEl) {
        // Ищем ВСЕ pre code блоки - по классу language-html ИЛИ по содержимому
        const allCodeBlocks = messageEl.querySelectorAll('pre code');
        allCodeBlocks.forEach(block => {
            // Пропускаем уже обработанные
            if (block.closest('.artifact-card')) return;
            const cls = block.className || '';
            const isHtmlClass = cls.includes('language-html') || cls.includes('language-htm') || cls.includes('lang-html');
            const rawText = block.textContent || '';
            const isHtmlContent = rawText.length > 100 && (
                rawText.includes('<!DOCTYPE') || rawText.includes('<!doctype') ||
                rawText.includes('<html') || rawText.includes('<HTML')
            );
            if (!isHtmlClass && !isHtmlContent) return;
            const html = rawText;
            const wrapper = document.createElement('div');
            wrapper.className = 'artifact-card';
            const header = `<div class="artifact-header"><span class="artifact-title">🌐 HTML Превью</span><div class="artifact-actions"><button class="art-btn active" data-view="preview">👁 Превью</button><button class="art-btn" data-view="code">💻 Код</button><button class="art-btn" data-view="open">↗ Открыть</button></div></div>`;
            const preview = `<div class="artifact-preview active"><iframe sandbox="allow-scripts allow-same-origin" style="width:100%;height:450px;border:none;background:#fff;border-radius:0 0 12px 12px"></iframe></div>`;
            const codeHtml = `<div class="artifact-code">${block.parentElement.outerHTML}</div>`;
            wrapper.innerHTML = header + preview + codeHtml;
            wrapper.querySelectorAll('.art-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const view = btn.dataset.view;
                    if (view === 'open') { const win = window.open('', '_blank'); win.document.write(html); win.document.close(); return; }
                    wrapper.querySelectorAll('.art-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    wrapper.querySelector('.artifact-preview').classList.toggle('active', view === 'preview');
                    wrapper.querySelector('.artifact-code').classList.toggle('active', view === 'code');
                });
            });
            wrapper.querySelector('iframe').srcdoc = html;
            block.parentElement.replaceWith(wrapper);
        });
    },

    renderMarkdown(text) {
        if (!text) return '';
        if (typeof marked !== 'undefined') {
            try {
                marked.setOptions({
                    breaks: true,
                    gfm: true,
                    highlight: (code, lang) => {
                        if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                            return hljs.highlight(code, { language: lang }).value;
                        }
                        return Utils.escapeHtml(code);
                    }
                });
                return marked.parse(text);
            } catch (e) {
                return Utils.escapeHtml(text).replace(/\n/g, '<br>');
            }
        }
        return Utils.escapeHtml(text).replace(/\n/g, '<br>');
    },

    highlightCode(container) {
        if (typeof hljs === 'undefined') return;
        container.querySelectorAll('pre code').forEach(block => {
            if (!block.dataset.highlighted) {
                hljs.highlightElement(block);
                block.dataset.highlighted = '1';
            }
        });
    },

    addCopyButtons(container) {
        container.querySelectorAll('pre').forEach(pre => {
            if (pre.querySelector('.code-copy-btn')) return;
            const btn = el('button', 'code-copy-btn', '📋 Копировать');
            btn.style.cssText = 'position:absolute;top:8px;right:8px';
            pre.style.position = 'relative';
            btn.addEventListener('click', () => {
                const code = pre.querySelector('code')?.textContent || pre.textContent;
                Utils.copyText(code).then(() => {
                    btn.textContent = '✅ Скопировано';
                    btn.classList.add('copied');
                    setTimeout(() => { btn.textContent = '📋 Копировать'; btn.classList.remove('copied'); }, 2000);
                });
            });
            pre.appendChild(btn);
        });
    },

    renderMeta(meta) {
        const div = el('div', 'msg-meta');
        div.innerHTML = `
            <span class="msg-meta-model">${meta.model || ''}</span>
            <span class="msg-meta-sep">·</span>
            <span class="msg-meta-cost">${Utils.formatCost(meta.cost)}</span>
            <span class="msg-meta-sep">·</span>
            <span>${Utils.formatDuration(meta.duration_ms || 0)}</span>
            ${meta.iterations ? `<span class="msg-meta-sep">·</span><span>${meta.iterations} итер.</span>` : ''}`;
        return div;
    },

    renderActions(content) {
        const div = el('div', 'msg-actions');
        const copyBtn = el('button', 'msg-action-btn', '📋 Копировать');
        copyBtn.addEventListener('click', () => {
            Utils.copyText(content).then(() => {
                copyBtn.textContent = '✅ Скопировано';
                copyBtn.classList.add('copied');
                setTimeout(() => { copyBtn.textContent = '📋 Копировать'; copyBtn.classList.remove('copied'); }, 2000);
            });
        });
        const regenBtn = el('button', 'msg-action-btn', '🔄 Повторить');
        regenBtn.addEventListener('click', () => Chat.regenerate());
        div.appendChild(copyBtn);
        div.appendChild(regenBtn);
        return div;
    },

    addArtifact(wrapper, evt) {
        const body = wrapper.querySelector('.msg-body');
        if (!body) return;
        const card = Artifacts.render(evt);
        if (card) body.appendChild(card);
    },

    addFollowups(wrapper, suggestions) {
        const body = wrapper.querySelector('.msg-body');
        if (!body || !suggestions.length) return;
        const wrap = el('div', 'followups-wrap');
        suggestions.forEach(s => {
            const chip = el('button', 'followup-chip', Utils.escapeHtml(s));
            chip.addEventListener('click', () => Chat.sendFromChip(s));
            wrap.appendChild(chip);
        });
        body.appendChild(wrap);
    },

    addTaskSummary(wrapper, evt) {
        const body = wrapper.querySelector('.msg-body');
        if (!body) return;
        const summary = el('div', 'task-summary');
        summary.innerHTML = `
            <div class="task-summary-title">✅ Задача выполнена</div>
            <div class="task-summary-stats">
                <span class="task-summary-stat">💰 ${Utils.formatCost(evt.cost)}</span>
                <span class="task-summary-stat">⏱ ${Utils.formatDuration(evt.duration_ms || 0)}</span>
                <span class="task-summary-stat">🔄 ${evt.iterations || 0} итераций</span>
            </div>
            ${evt.agents?.length ? `<div class="task-summary-agents">👥 ${evt.agents.map(a => `<span class="agent-badge">${a}</span>`).join('')}</div>` : ''}`;
        body.appendChild(summary);
    }
};



/* ── VOICE INPUT ──────────────────────────────────────── */
const VoiceInput = {
    recognition: null,
    isListening: false,

    init() {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) return;
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.recognition = new SR();
        this.recognition.lang = 'ru-RU';
        this.recognition.interimResults = true;
        this.recognition.continuous = true;

        this.recognition.onresult = (event) => {
            let final = '', interim = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                if (event.results[i].isFinal) {
                    final += event.results[i][0].transcript;
                } else {
                    interim += event.results[i][0].transcript;
                }
            }
            const textarea = document.querySelector('#message-input');
            if (textarea) {
                if (final) textarea.value += final + ' ';
                const indicator = document.getElementById('voice-interim');
                if (indicator) indicator.textContent = interim;
            }
        };

        this.recognition.onend = () => {
            if (this.isListening) this.recognition.start();
        };
    },

    toggle() {
        if (!this.recognition) {
            alert('Голосовой ввод не поддерживается в этом браузере');
            return;
        }
        if (this.isListening) this.stop(); else this.start();
    },

    start() {
        this.isListening = true;
        this.recognition.start();
        const btn = document.getElementById('btn-voice');
        if (btn) { btn.classList.add('voice-active'); btn.title = 'Остановить запись'; }
    },

    stop() {
        this.isListening = false;
        this.recognition.stop();
        const btn = document.getElementById('btn-voice');
        if (btn) { btn.classList.remove('voice-active'); btn.title = 'Голосовой ввод'; }
        const indicator = document.getElementById('voice-interim');
        if (indicator) indicator.textContent = '';
    }
};

/* ── ARTIFACT MANAGER (iterative editing) ──────────────── */
const ArtifactManager = {
    artifacts: {},
    history: {},

    create(id, html, type, filename) {
        const el = document.querySelector(`[data-artifact-id="${id}"]`);
        if (el) {
            this.update(id, html);
            return;
        }
        this.artifacts[id] = { html, type, filename };
    },

    update(id, newHtml) {
        const art = this.artifacts[id];
        if (!art) return;
        if (!this.history[id]) this.history[id] = [];
        this.history[id].push(art.html);
        art.html = newHtml;
        const iframe = document.querySelector(`[data-artifact-id="${id}"] iframe`);
        if (iframe) iframe.srcdoc = newHtml;
        const code = document.querySelector(`[data-artifact-id="${id}"] .artifact-code code`);
        if (code) code.textContent = newHtml;
        const card = document.querySelector(`[data-artifact-id="${id}"]`);
        if (card) {
            card.classList.add('artifact-updated');
            setTimeout(() => card.classList.remove('artifact-updated'), 1000);
        }
    },

    undo(id) {
        if (this.history[id] && this.history[id].length > 0) {
            const prev = this.history[id].pop();
            this.artifacts[id].html = prev;
            const iframe = document.querySelector(`[data-artifact-id="${id}"] iframe`);
            if (iframe) iframe.srcdoc = prev;
        }
    }
};

/* ── ARTIFACTS ────────────────────────────────────────────── */
const Artifacts = {
    render(evt) {
        switch (evt.artifact_type) {
            case 'html': return this.renderHTML(evt);
            case 'image': return this.renderImage(evt);
            case 'script':
            case 'code': return this.renderScript(evt);
            case 'document':
            case 'pdf':
            case 'docx': return this.renderDocument(evt);
            default: return null;
        }
    },

    renderHTML(evt) {
        const card = el('div', 'artifact-card');
        const filename = evt.filename || 'index.html';
        const htmlContent = evt.html_content || evt.content || '';
        let showPreview = true;

        card.innerHTML = `
            <div class="artifact-header">
                <span class="artifact-icon">🌐</span>
                <span class="artifact-title">${Utils.escapeHtml(filename)}</span>
                <div class="artifact-tabs">
                    <button class="artifact-tab active" data-tab="preview">Превью</button>
                    <button class="artifact-tab" data-tab="code">Код</button>
                </div>
                <div class="artifact-actions">
                    <button class="artifact-action-btn" title="Копировать">📋</button>
                    <button class="artifact-action-btn" title="Открыть">↗️</button>
                </div>
            </div>
            <div class="artifact-body">
                <div class="artifact-preview-wrap">
                    <iframe class="artifact-preview-frame" sandbox="allow-scripts allow-same-origin"></iframe>
                </div>
                <div class="artifact-code-view hidden">
                    <pre><code class="language-html">${Utils.escapeHtml(htmlContent)}</code></pre>
                </div>
            </div>`;

        const iframe = card.querySelector('iframe');
        const previewWrap = card.querySelector('.artifact-preview-wrap');
        const codeView = card.querySelector('.artifact-code-view');
        const tabs = card.querySelectorAll('.artifact-tab');

        // Load iframe
        if (htmlContent) {
            const blob = new Blob([htmlContent], { type: 'text/html' });
            iframe.src = URL.createObjectURL(blob);
        }

        // Tab switching
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const isPreview = tab.dataset.tab === 'preview';
                previewWrap.classList.toggle('hidden', !isPreview);
                codeView.classList.toggle('hidden', isPreview);
                if (!isPreview && typeof hljs !== 'undefined') {
                    const codeEl = codeView.querySelector('code');
                    if (codeEl && !codeEl.dataset.highlighted) {
                        hljs.highlightElement(codeEl);
                        codeEl.dataset.highlighted = '1';
                    }
                }
            });
        });

        // Actions
        const [copyBtn, openBtn] = card.querySelectorAll('.artifact-action-btn');
        copyBtn.addEventListener('click', () => {
            Utils.copyText(htmlContent).then(() => { copyBtn.textContent = '✅'; setTimeout(() => copyBtn.textContent = '📋', 2000); });
        });
        openBtn.addEventListener('click', () => {
            const blob = new Blob([htmlContent], { type: 'text/html' });
            window.open(URL.createObjectURL(blob), '_blank');
        });

        return card;
    },

    renderImage(evt) {
        const card = el('div', 'artifact-card');
        const src = evt.url || evt.src || evt.image_url || '';
        const filename = evt.filename || 'image.png';
        card.innerHTML = `
            <div class="artifact-header">
                <span class="artifact-icon">🖼️</span>
                <span class="artifact-title">${Utils.escapeHtml(filename)}</span>
                <div class="artifact-actions">
                    <a class="artifact-action-btn" href="${src}" download="${filename}">⬇️ Скачать</a>
                </div>
            </div>
            <img class="artifact-image" src="${src}" alt="${Utils.escapeHtml(filename)}" loading="lazy">`;
        card.querySelector('img').addEventListener('click', () => Lightbox.open(src));
        return card;
    },

    renderScript(evt) {
        const card = el('div', 'artifact-card');
        const filename = evt.filename || 'script.py';
        const content = evt.content || '';
        const lines = content.split('\n');
        const preview = lines.slice(0, 10).join('\n');
        const hasMore = lines.length > 10;
        const lang = filename.split('.').pop() || 'python';

        card.innerHTML = `
            <div class="artifact-header">
                <span class="artifact-icon">💻</span>
                <span class="artifact-title">${Utils.escapeHtml(filename)}</span>
                <div class="artifact-actions">
                    <button class="artifact-action-btn">📋 Копировать</button>
                </div>
            </div>
            <div class="artifact-script-preview">
                <pre class="artifact-code-view" style="max-height:200px;overflow:hidden"><code class="language-${lang}">${Utils.escapeHtml(preview)}</code></pre>
                ${hasMore ? `<button class="artifact-expand-btn">▼ Показать все ${lines.length} строк</button>` : ''}
            </div>`;

        const copyBtn = card.querySelector('.artifact-action-btn');
        copyBtn.addEventListener('click', () => {
            Utils.copyText(content).then(() => { copyBtn.textContent = '✅ Скопировано'; setTimeout(() => copyBtn.textContent = '📋 Копировать', 2000); });
        });

        if (hasMore) {
            const expandBtn = card.querySelector('.artifact-expand-btn');
            const pre = card.querySelector('pre');
            expandBtn.addEventListener('click', () => {
                pre.querySelector('code').textContent = content;
                pre.style.maxHeight = 'none';
                expandBtn.remove();
                if (typeof hljs !== 'undefined') hljs.highlightElement(pre.querySelector('code'));
            });
        }

        if (typeof hljs !== 'undefined') {
            const codeEl = card.querySelector('code');
            if (codeEl) hljs.highlightElement(codeEl);
        }

        return card;
    },

    renderDocument(evt) {
        const card = el('div', 'artifact-card');
        const filename = evt.filename || 'document.pdf';
        const size = evt.size ? Utils.formatSize(evt.size) : '';
        const url = evt.url || evt.download_url || '#';
        const icon = Utils.getFileIcon(filename);
        const isPDF = filename.toLowerCase().endsWith('.pdf');

        card.innerHTML = `
            <div class="artifact-header">
                <span class="artifact-icon">${icon}</span>
                <span class="artifact-title">${Utils.escapeHtml(filename)}</span>
            </div>
            <div class="artifact-doc">
                <div class="artifact-doc-icon">${icon}</div>
                <div class="artifact-doc-info">
                    <div class="artifact-doc-name">${Utils.escapeHtml(filename)}</div>
                    ${size ? `<div class="artifact-doc-size">${size}</div>` : ''}
                </div>
                <a class="btn btn-primary btn-sm" href="${url}" download="${filename}">⬇️ Скачать</a>
            </div>
            ${isPDF && url && url !== '#' ? '<div class="pdf-preview" id="pdf-preview-' + Utils.generateId() + '"><div class="pdf-header">📄 Предпросмотр PDF</div><div class="pdf-pages"></div></div>' : ''}`;

        // PDF.js preview rendering
        if (isPDF && url && url !== '#') {
            const previewEl = card.querySelector('.pdf-pages');
            if (previewEl && typeof pdfjsLib !== 'undefined') {
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
                pdfjsLib.getDocument(url).promise.then(pdfDoc => {
                    const totalPages = Math.min(pdfDoc.numPages, 3);
                    for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
                        pdfDoc.getPage(pageNum).then(page => {
                            const viewport = page.getViewport({ scale: 1.2 });
                            const pageDiv = document.createElement('div');
                            pageDiv.className = 'pdf-page-preview';
                            const canvas = document.createElement('canvas');
                            canvas.width = viewport.width;
                            canvas.height = viewport.height;
                            const numLabel = document.createElement('span');
                            numLabel.className = 'pdf-page-num';
                            numLabel.textContent = 'Стр. ' + pageNum;
                            pageDiv.appendChild(canvas);
                            pageDiv.appendChild(numLabel);
                            previewEl.appendChild(pageDiv);
                            page.render({ canvasContext: canvas.getContext('2d'), viewport });
                        });
                    }
                    if (pdfDoc.numPages > 3) {
                        const more = document.createElement('div');
                        more.className = 'pdf-more';
                        more.textContent = `+ ещё ${pdfDoc.numPages - 3} стр. — скачайте для просмотра`;
                        previewEl.appendChild(more);
                    }
                }).catch(err => {
                    previewEl.innerHTML = '<div class="pdf-more">Предпросмотр недоступен</div>';
                });
            }
        }
        return card;
    }
};

/* ── PROJECT TEMPLATES UI ────────────────────────────────── */
const Templates = {
    open() {
        let modal = document.getElementById('templates-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'templates-modal';
            modal.className = 'modal-overlay';
            modal.innerHTML = `
                <div class="modal modal-sm" style="max-width:560px">
                    <div class="modal-header">
                        <h2 class="modal-title">📋 Шаблоны проектов</h2>
                        <button class="btn-modal-close" id="btn-templates-close">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                    </div>
                    <div class="modal-body">
                        <p style="color:var(--text-secondary);font-size:13px;margin-bottom:16px">Выберите шаблон для быстрого старта проекта</p>
                        <div class="templates-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
                            ${PROJECT_TEMPLATES.map(t => `
                                <button class="template-card" data-prompt="${t.prompt.replace(/"/g, '&quot;')}" style="display:flex;align-items:center;gap:10px;padding:12px 14px;border:1px solid var(--border);border-radius:10px;background:var(--bg-secondary);cursor:pointer;text-align:left;transition:all 0.15s">
                                    <span style="font-size:22px">${t.icon}</span>
                                    <span style="font-size:13px;font-weight:500;color:var(--text-primary)">${t.name}</span>
                                </button>`).join('')}
                        </div>
                    </div>
                </div>`;
            document.body.appendChild(modal);
            modal.querySelector('#btn-templates-close').addEventListener('click', () => this.close());
            modal.addEventListener('click', e => { if (e.target === modal) this.close(); });
            modal.querySelectorAll('.template-card').forEach(btn => {
                btn.addEventListener('mouseenter', () => { btn.style.borderColor = 'var(--accent)'; btn.style.background = 'var(--bg-hover)'; });
                btn.addEventListener('mouseleave', () => { btn.style.borderColor = 'var(--border)'; btn.style.background = 'var(--bg-secondary)'; });
                btn.addEventListener('click', () => {
                    const prompt = btn.getAttribute('data-prompt');
                    this.close();
                    if (prompt) Chat.sendFromChip(prompt);
                });
            });
        }
        modal.classList.remove('hidden');
    },
    close() {
        const modal = document.getElementById('templates-modal');
        if (modal) modal.classList.add('hidden');
    }
};
window.Templates = Templates;

/* ── ACTIVITY PANEL ───────────────────────────────────────── */
const ActivityPanel = {
    show(agentName = '') {
        const panel = $('activity-panel');
        if (panel) panel.classList.remove('hidden');
        state.activityVisible = true;
        if (agentName) {
            const nameEl = document.querySelector('.activity-agent-name');
            if (nameEl) nameEl.textContent = agentName;
        }
    },

    hide() {
        const panel = $('activity-panel');
        if (panel) panel.classList.add('hidden');
        state.activityVisible = false;
    },

    toggle() {
        if (state.activityVisible) this.hide();
        else this.show();
    },

    clear() {
        const log = $('activity-log');
        if (log) {
            log.innerHTML = '';
            // BUG-4 FIX: restore empty placeholder
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'activity-empty';
            emptyDiv.innerHTML = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg><p>Активность агента появится здесь</p>';
            log.appendChild(emptyDiv);
        }
        state.activityLines = [];
        this.updateProgress(0, 0, []);
        this.hideTakeover();
    },

    setStatus(status) {
        // BUG-6 FIX: HTML uses .status-dot and #status-text, not .status-pulse
        const dotEl = document.querySelector('.status-dot');
        const textEl = $('status-text');
        const labels = { running: 'Работает', done: 'Завершено', waiting: 'Ожидает', idle: 'Ожидает' };
        if (dotEl) dotEl.className = 'status-dot ' + status;
        if (textEl) textEl.textContent = labels[status] || status;
    },

    addLine(type, emoji, text, collapsible = false) {
        const log = $('activity-log');
        if (!log) return;

        // BUG-4 FIX: remove empty placeholder on first line
        const emptyEl = log.querySelector('.activity-empty');
        if (emptyEl) emptyEl.remove();

        const line = el('div', 'activity-line ' + type);
        const time = el('span', 'activity-time', Utils.formatTime());
        const emojiEl = el('span', 'activity-emoji', emoji);
        const content = el('div', 'activity-content');

        if (collapsible && text.length > 200) {
            const preview = text.slice(0, 200);
            const resultEl = el('div', 'activity-result', Utils.escapeHtml(preview));
            const toggle = el('span', 'activity-result-toggle', '▼ Показать полностью');
            toggle.addEventListener('click', () => {
                resultEl.textContent = text;
                resultEl.classList.add('expanded');
                toggle.remove();
            });
            content.appendChild(resultEl);
            content.appendChild(toggle);
        } else {
            const textEl = el('div', 'activity-text', Utils.escapeHtml(text));
            content.appendChild(textEl);
        }

        line.appendChild(time);
        line.appendChild(emojiEl);
        line.appendChild(content);
        log.appendChild(line);

        state.activityLines.push({ type, emoji, text, time: new Date() });
        log.scrollTop = log.scrollHeight;
    },

    renderTaskProgress() {
        // ПАТЧ W2-2: Рендер Task Progress как у Manus
        const panel = $('activity-log');
        if (!panel) return;

        let container = document.querySelector('.task-progress-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'task-progress-container';
            container.style.cssText = 'padding: 8px 12px; border-bottom: 1px solid var(--border, #333); margin-bottom: 8px;';
            panel.insertBefore(container, panel.firstChild);
        }

        const tp = state.taskProgress;
        if (!tp || !tp.steps) return;

        let html = `<div style="font-size:12px;font-weight:600;margin-bottom:6px;color:var(--text-primary,#eee);">
            Task progress <span style="color:var(--text-secondary,#888)">${tp.current} / ${tp.total}</span>
        </div>`;

        tp.steps.forEach((step, i) => {
            let icon = '○';
            let color = 'var(--text-tertiary, #555)';
            if (step.status === 'done') { icon = '✅'; color = 'var(--text-primary, #eee)'; }
            else if (step.status === 'running') { icon = '⏳'; color = '#7c5cfc'; }
            else if (step.status === 'error') { icon = '❌'; color = '#f87171'; }

            html += `<div style="display:flex;align-items:flex-start;gap:6px;padding:3px 0;font-size:11px;color:${color};">
                <span style="flex-shrink:0;width:18px;text-align:center;">${icon}</span>
                <span>${step.name}</span>
            </div>`;
        });

        container.innerHTML = html;
    },

    addCodeBlock(filename, content) {
        const log = $('activity-log');
        if (!log) return;

        const line = el('div', 'activity-line file-write');
        const time = el('span', 'activity-time', Utils.formatTime());
        const emojiEl = el('span', 'activity-emoji', '📝');
        const content_wrap = el('div', 'activity-content');

        const label = el('div', 'activity-tool', 'Создаю ' + filename);
        const block = el('div', 'activity-code-block');
        const lines = content.split('\n');
        const preview = lines.slice(0, 10).join('\n');
        const hasMore = lines.length > 10;

        block.innerHTML = `
            <div class="activity-code-header">
                <span class="activity-code-filename">${Utils.escapeHtml(filename)}</span>
                <button class="code-copy-btn" style="font-size:10px;padding:2px 6px">📋</button>
            </div>
            <div class="activity-code-body">${Utils.escapeHtml(preview)}</div>
            ${hasMore ? `<div class="activity-code-expand">▼ Ещё ${lines.length - 10} строк</div>` : ''}`;

        const copyBtn = block.querySelector('.code-copy-btn');
        copyBtn.addEventListener('click', () => {
            Utils.copyText(content).then(() => { copyBtn.textContent = '✅'; setTimeout(() => copyBtn.textContent = '📋', 2000); });
        });

        if (hasMore) {
            const expandBtn = block.querySelector('.activity-code-expand');
            const bodyEl = block.querySelector('.activity-code-body');
            expandBtn.addEventListener('click', () => {
                bodyEl.textContent = content;
                bodyEl.classList.add('expanded');
                expandBtn.remove();
            });
        }

        content_wrap.appendChild(label);
        content_wrap.appendChild(block);
        line.appendChild(time);
        line.appendChild(emojiEl);
        line.appendChild(content_wrap);
        log.appendChild(line);
        log.scrollTop = log.scrollHeight;
    },

    addScreenshot(url, screenshotData, status) {
        const log = $('activity-log');
        if (!log) return;

        const line = el('div', 'activity-line browser');
        const time = el('span', 'activity-time', Utils.formatTime());
        const emojiEl = el('span', 'activity-emoji', '🌐');
        const content = el('div', 'activity-content');

        const label = el('div', 'activity-tool', 'Открываю ' + url);
        content.appendChild(label);

        if (screenshotData) {
            const screenshot = el('div', 'activity-screenshot');
            const src = screenshotData.startsWith('data:') ? screenshotData : 'data:image/png;base64,' + screenshotData;
            screenshot.innerHTML = `
                <div class="activity-screenshot-header">
                    <span>${Utils.escapeHtml(url)}</span>
                    <span>${status || ''}</span>
                </div>
                <img src="${src}" alt="Screenshot" loading="lazy">
                ${status ? `<div class="activity-screenshot-status">${Utils.escapeHtml(status)}</div>` : ''}`;
            screenshot.querySelector('img').addEventListener('click', () => Lightbox.open(src));
            content.appendChild(screenshot);
        }

        line.appendChild(time);
        line.appendChild(emojiEl);
        line.appendChild(content);
        log.appendChild(line);
        log.scrollTop = log.scrollHeight;
    },

    updateProgress(current, total, steps = []) {
        state.taskProgress = { current, total, steps };
        const progressEl = document.querySelector('.task-progress');
        if (!progressEl) return;

        if (!total) { progressEl.style.display = 'none'; return; }
        progressEl.style.display = '';

        const fill = progressEl.querySelector('.progress-fill, .progress-bar-fill') || $('progress-fill');
        const label = progressEl.querySelector('.progress-label');
        const stepsEl = progressEl.querySelector('.progress-steps');

        if (fill) fill.style.width = Math.round((current / total) * 100) + '%';
        if (label) label.textContent = `Итерация ${current} / ${total}`;

        if (stepsEl && steps.length) {
            stepsEl.innerHTML = steps.map(s => `
                <div class="progress-step ${s.status}">
                    <span class="step-icon">${s.status === 'done' ? '✅' : s.status === 'active' ? '⏳' : '○'}</span>
                    ${Utils.escapeHtml(s.name)}
                </div>`).join('');
        }
    },

    showTakeover(message, screenshotData) {
        const panel = $('activity-panel');
        if (!panel) return;
        this.show();

        let banner = panel.querySelector('.takeover-banner');
        if (!banner) {
            banner = el('div', 'takeover-banner');
            panel.appendChild(banner);
        }

        banner.innerHTML = `
            <div class="takeover-title">⚠️ Агент нуждается в помощи</div>
            <div class="takeover-desc">${Utils.escapeHtml(message)}</div>
            ${screenshotData ? `<img src="${screenshotData.startsWith('data:') ? screenshotData : 'data:image/png;base64,' + screenshotData}" style="width:100%;border-radius:6px;margin-bottom:8px;cursor:zoom-in" onclick="Lightbox.open(this.src)">` : ''}
            <input type="text" class="takeover-input" id="takeover-input" placeholder="Введите ответ (капча, пароль, данные...)">
            <button class="btn-takeover-send" id="btn-takeover-send">Отправить агенту</button>`;

        const sendBtn = banner.querySelector('#btn-takeover-send');
        if (sendBtn) sendBtn.addEventListener('click', () => this.sendTakeover());
    },

    hideTakeover() {
        const banner = document.querySelector('.takeover-banner');
        if (banner) banner.remove();
    },

    async sendTakeover() {
        const input = $('takeover-input');
        if (!input) return;
        const value = input.value.trim();
        if (!value) return;

        try {
            await API.post('/chats/' + state.currentChatId + '/takeover', { response: value });
            this.hideTakeover();
            this.addLine('success', '✅', 'Ответ отправлен агенту: ' + value);
            Toast.show('Ответ отправлен', 'success');
        } catch (e) {
            Toast.show('Ошибка отправки: ' + e.message, 'error');
        }
    }
};

/* ── ATTACHMENTS ──────────────────────────────────────────── */
const Attachments = {
    async handleFiles(files) {
        for (const file of files) {
            if (state.attachments.length >= 10) {
                Toast.show('Максимум 10 файлов', 'warning');
                break;
            }
            const att = {
                id: Utils.generateId(),
                name: file.name,
                size: file.size,
                type: file.type,
                file
            };
            if (Utils.isImage(file.name)) {
                att.preview = await this.readAsDataURL(file);
            }
            state.attachments.push(att);
        }
        this.renderPreviews();
        // Reset file input
        const fi = $('file-input');
        if (fi) fi.value = '';
    },

    readAsDataURL(file) {
        return new Promise(resolve => {
            const reader = new FileReader();
            reader.onload = e => resolve(e.target.result);
            reader.readAsDataURL(file);
        });
    },

    renderPreviews() {
        const container = document.querySelector('.attachments-preview');
        if (!container) return;
        container.innerHTML = '';
        if (!state.attachments.length) { container.style.display = 'none'; return; }
        container.style.display = 'flex';

        state.attachments.forEach((att, idx) => {
            const item = el('div', 'attachment-item');
            if (att.preview) {
                item.innerHTML = `<img class="attachment-thumb" src="${att.preview}" alt="${Utils.escapeHtml(att.name)}">`;
            } else {
                item.innerHTML = `<div class="attachment-icon">${Utils.getFileIcon(att.name)}</div>`;
            }
            item.innerHTML += `
                <div class="attachment-info">
                    <div class="attachment-name">${Utils.escapeHtml(att.name)}</div>
                    <div class="attachment-size">${Utils.formatSize(att.size)}</div>
                </div>
                <button class="attachment-remove" data-idx="${idx}">✕</button>`;
            item.querySelector('.attachment-remove').addEventListener('click', () => {
                state.attachments.splice(idx, 1);
                this.renderPreviews();
            });
            container.appendChild(item);
        });
    },

    showDropOverlay() {
        const overlay = document.querySelector('.drop-overlay, .drop-zone-overlay, #drop-zone-overlay');
        if (overlay) overlay.classList.add('active');
    },

    hideDropOverlay() {
        const overlay = document.querySelector('.drop-overlay, .drop-zone-overlay, #drop-zone-overlay');
        if (overlay) overlay.classList.remove('active');
    }
};

/* ── LIGHTBOX ─────────────────────────────────────────────── */
const Lightbox = {
    open(src) {
        const lb = $('lightbox');
        if (!lb) return;
        const img = lb.querySelector('img');
        if (img) img.src = src;
        lb.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    },
    close() {
        const lb = $('lightbox');
        if (lb) lb.classList.add('hidden');
        document.body.style.overflow = '';
    }
};

/* ── TOAST ────────────────────────────────────────────────── */
const Toast = {
    show(message, type = 'info', duration = 3000) {
        const container = $('toast-container') || document.querySelector('.toast-container');
        if (!container) return;
        const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
        const toast = el('div', 'toast ' + type);
        toast.innerHTML = `<span class="toast-icon">${icons[type] || 'ℹ️'}</span><span class="toast-text">${Utils.escapeHtml(message)}</span>`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            toast.style.transition = 'all 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
};


// ── SSH Settings Management ──
const SSHSettings = {
    servers: [],
    init() {
        this.servers = JSON.parse(localStorage.getItem('orion_ssh_servers') || '[]');
        const addBtn = document.getElementById('btn-add-ssh');
        const saveBtn = document.getElementById('btn-save-ssh');
        const cancelBtn = document.getElementById('btn-cancel-ssh');
        if (addBtn) addBtn.addEventListener('click', () => {
            document.getElementById('ssh-add-form').classList.remove('hidden');
        });
        if (cancelBtn) cancelBtn.addEventListener('click', () => {
            document.getElementById('ssh-add-form').classList.add('hidden');
        });
        if (saveBtn) saveBtn.addEventListener('click', () => this.saveServer());
        this.render();
    },
    saveServer() {
        const host = document.getElementById('ssh-host').value.trim();
        const user = document.getElementById('ssh-user').value.trim();
        const port = parseInt(document.getElementById('ssh-port').value) || 22;
        const password = document.getElementById('ssh-password').value;
        if (!host || !user) { alert('Укажите хост и логин'); return; }
        this.servers.push({ host, user, port, password, id: Date.now().toString() });
        localStorage.setItem('orion_ssh_servers', JSON.stringify(this.servers));
        document.getElementById('ssh-add-form').classList.add('hidden');
        document.getElementById('ssh-host').value = '';
        document.getElementById('ssh-user').value = '';
        document.getElementById('ssh-port').value = '22';
        document.getElementById('ssh-password').value = '';
        this.render();
    },
    removeServer(id) {
        this.servers = this.servers.filter(s => s.id !== id);
        localStorage.setItem('orion_ssh_servers', JSON.stringify(this.servers));
        this.render();
    },
    render() {
        const container = document.getElementById('ssh-servers-container');
        if (!container) return;
        if (this.servers.length === 0) {
            container.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;">Нет сохранённых серверов</div>';
            return;
        }
        container.innerHTML = this.servers.map(s => `
            <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 10px;background:var(--bg-primary);border-radius:6px;margin-bottom:4px;font-size:13px;">
                <span>${s.user}@${s.host}:${s.port}</span>
                <button onclick="SSHSettings.removeServer('${s.id}')" style="background:none;border:none;color:var(--danger);cursor:pointer;font-size:16px;" title="Удалить">×</button>
            </div>
        `).join('');
    },
    getServers() { return this.servers; }
};

/* ── ADMIN PANEL ──────────────────────────────────────────── */
const AdminPanel = {
    currentTab: 'users',
    chart: null,

    async open() {
        if (!state.user || state.user.role !== 'admin') return;
        const modal = $('admin-modal');
        if (modal) modal.classList.remove('hidden');
        await this.loadTab('users');
    },

    close() {
        const modal = $('admin-modal');
        if (modal) modal.classList.add('hidden');
        if (this.chart) { this.chart.destroy(); this.chart = null; }
    },

    async loadTab(tab) {
        // BUG-7 FIX: HTML uses .tab-btn and #tab-{name}, not .modal-tab and #admin-tab-{name}
        this.currentTab = tab;
        $$('.tab-btn').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        $$('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + tab));

        switch (tab) {
            case 'users': await this.loadUsers(); break;
            case 'chats': await this.loadAllChats(); break;
            case 'analytics': await this.loadAnalytics(); break;
        }
    },

    async loadUsers() {
        const container = $('tab-users');
        if (!container) return;
        container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

        try {
            const data = await API.get('/admin/users');
            let rawUsers = data.users || data || [];
            // BUG-6 FIX: Normalize API fields to frontend expectations
            state.adminData.users = rawUsers.map(u => ({
                ...u,
                full_name: u.full_name || u.name || u.email || '',
                username: u.username || u.email || '',
                is_blocked: u.is_blocked !== undefined ? u.is_blocked : !u.is_active
            }));
            this.renderUsers(state.adminData.users);
        } catch (e) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-desc">Ошибка: ${Utils.escapeHtml(e.message)}</div></div>`;
        }
    },

    renderUsers(users) {
        const container = $('tab-users');
        if (!container) return;

        const html = `
            <div style="display:flex;justify-content:flex-end;margin-bottom:16px">
                <button class="btn btn-primary btn-sm" onclick="AdminPanel.showCreateUser()">+ Создать пользователя</button>
            </div>
            <div style="overflow-x:auto">
                <table class="admin-table">
                    <thead>
                        <tr>
                            <th>Пользователь</th>
                            <th>Роль</th>
                            <th>Создан</th>
                            <th>Потрачено</th>
                            <th>Лимит</th>
                            <th>Статус</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${users.map(u => `
                            <tr>
                                <td>
                                    <div class="user-cell">
                                        <div class="user-cell-avatar">${(u.full_name || u.username || 'U')[0].toUpperCase()}</div>
                                        <div>
                                            <div style="font-weight:500">${Utils.escapeHtml(u.full_name || u.username)}</div>
                                            <div style="font-size:11px;color:var(--text-tertiary)">${Utils.escapeHtml(u.username)}</div>
                                        </div>
                                    </div>
                                </td>
                                <td><span class="role-badge ${u.role}">${u.role === 'admin' ? 'Админ' : 'Пользователь'}</span></td>
                                <td style="font-size:12px;color:var(--text-secondary)">${Utils.formatDate(u.created_at)}</td>
                                <td style="color:var(--success);font-weight:500">${Utils.formatCost(u.total_spent)}</td>
                                <td style="font-size:12px">$${(u.monthly_limit || 0).toFixed(2)}</td>
                                <td><span class="status-badge ${u.is_blocked ? 'blocked' : 'active'}">${u.is_blocked ? 'Заблокирован' : 'Активен'}</span></td>
                                <td>
                                    <div class="table-actions">
                                        <button class="table-action-btn edit" onclick="AdminPanel.showEditUser('${u.id}')">Изменить</button>
                                        <button class="table-action-btn block" onclick="AdminPanel.toggleBlock('${u.id}', ${u.is_blocked})">${u.is_blocked ? 'Разблокировать' : 'Заблокировать'}</button>
                                    </div>
                                </td>
                            </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
        container.innerHTML = html;
    },

    async loadAllChats() {
        const container = $('tab-chats');
        if (!container) return;
        container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

        try {
            const data = await API.get('/admin/chats');
            state.adminData.chats = data.chats || data || [];
            this.renderAllChats(state.adminData.chats);
        } catch (e) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-desc">Ошибка: ${Utils.escapeHtml(e.message)}</div></div>`;
        }
    },

    renderAllChats(chats) {
        const container = $('tab-chats');
        if (!container) return;

        const html = `
            <div style="margin-bottom:12px">
                <input type="text" class="form-input" placeholder="Фильтр по пользователю..." oninput="AdminPanel.filterChats(this.value)" style="max-width:300px">
            </div>
            <div style="overflow-x:auto">
                <table class="admin-table">
                    <thead>
                        <tr>
                            <th>Пользователь</th>
                            <th>Чат</th>
                            <th>Дата</th>
                            <th>Сообщений</th>
                            <th>Стоимость</th>
                            <th>Режим</th>
                        </tr>
                    </thead>
                    <tbody id="admin-chats-tbody">
                        ${chats.map(c => `
                            <tr data-user="${Utils.escapeHtml((c.user_name || c.user_email || c.username || '').toLowerCase())}">
                                <td style="font-size:12px;font-weight:500">${Utils.escapeHtml(c.user_name || c.user_email || c.username || '—')}</td>
                                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(c.title || 'Без названия')}</td>
                                <td style="font-size:12px;color:var(--text-secondary)">${Utils.formatDate(c.created_at)}</td>
                                <td style="text-align:center">${c.message_count || 0}</td>
                                <td style="color:var(--success);font-weight:500">${Utils.formatCost(c.total_cost)}</td>
                                <td style="font-size:11px;color:var(--text-tertiary)">${Utils.escapeHtml(c.variant || c.model || c.mode || '—')}</td>
                            </tr>`).join('')}
                    </tbody>
                </table>
            </div>`;
        container.innerHTML = html;
    },

    filterChats(query) {
        const q = query.toLowerCase().trim();
        const rows = document.querySelectorAll('#admin-chats-tbody tr');
        rows.forEach(row => {
            row.style.display = !q || row.dataset.user.includes(q) ? '' : 'none';
        });
    },

    async loadAnalytics() {
        const container = $('tab-analytics');
        if (!container) return;
        container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

        try {
            const raw = await API.get('/admin/stats');  // BUG-3 FIX: backend uses /admin/stats
            // Normalize backend stats to frontend analytics format
            const dailyStats = raw.daily_stats || {};
            const today = new Date().toISOString().slice(0, 10);
            const todayData = dailyStats[today] || {};
            const data = {
                today: todayData.cost || 0,
                today_requests: todayData.requests || 0,
                week: raw.total_cost || 0,
                week_requests: raw.total_requests || 0,
                month: raw.total_cost || 0,
                month_requests: raw.total_requests || 0,
                total_users: raw.total_users || 0,
                total_chats: raw.total_chats || 0,
                total_messages: raw.total_messages || 0,
                total_cost: raw.total_cost || 0,
                daily: Object.entries(dailyStats).sort().map(([date, d]) => ({ date, cost: d.cost || 0, requests: d.requests || 0 })),
                top_users: [],
                model_breakdown: []
            };
            state.adminData.analytics = data;
            this.renderAnalytics(data);
        } catch (e) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-desc">Ошибка: ${Utils.escapeHtml(e.message)}</div></div>`;
        }
    },

    renderAnalytics(data) {
        const container = $('tab-analytics');
        if (!container) return;

        container.innerHTML = `
            <div class="analytics-grid">
                <div class="analytics-card">
                    <div class="analytics-card-label">Сегодня</div>
                    <div class="analytics-card-value">${Utils.formatCost(data.today || 0)}</div>
                    <div class="analytics-card-sub">${data.today_requests || 0} запросов</div>
                </div>
                <div class="analytics-card">
                    <div class="analytics-card-label">Всего расходов</div>
                    <div class="analytics-card-value">${Utils.formatCost(data.total_cost || 0)}</div>
                    <div class="analytics-card-sub">${data.month_requests || 0} запросов</div>
                </div>
                <div class="analytics-card">
                    <div class="analytics-card-label">Пользователей</div>
                    <div class="analytics-card-value">${data.total_users || 0}</div>
                    <div class="analytics-card-sub">${data.total_chats || 0} чатов</div>
                </div>
            </div>
            <div class="analytics-chart-wrap">
                <div class="analytics-chart-title">Расходы за 30 дней</div>
                <canvas id="analytics-chart" height="200"></canvas>
            </div>
            ${data.top_users?.length ? `
            <div class="analytics-chart-wrap">
                <div class="analytics-chart-title">Топ пользователей по расходам</div>
                <table class="admin-table">
                    <thead><tr><th>Пользователь</th><th>Потрачено</th><th>Запросов</th></tr></thead>
                    <tbody>
                        ${data.top_users.map(u => `
                            <tr>
                                <td>${Utils.escapeHtml(u.username)}</td>
                                <td style="color:var(--success);font-weight:500">${Utils.formatCost(u.total_spent)}</td>
                                <td>${u.request_count || 0}</td>
                            </tr>`).join('')}
                    </tbody>
                </table>
            </div>` : ''}
            ${data.model_breakdown?.length ? `
            <div class="analytics-chart-wrap">
                <div class="analytics-chart-title">Разбивка по моделям</div>
                <canvas id="models-chart" height="150"></canvas>
            </div>` : ''}`;

        // Render Chart.js charts
        if (typeof Chart !== 'undefined') {
            this.renderDailyChart(data.daily || []);
            if (data.model_breakdown?.length) this.renderModelsChart(data.model_breakdown);
        }
    },

    renderDailyChart(daily) {
        const canvas = $('analytics-chart');
        if (!canvas) return;
        if (this.chart) this.chart.destroy();
        const isDark = state.theme === 'dark';
        this.chart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: daily.map(d => d.date),
                datasets: [{
                    label: 'Расходы ($)',
                    data: daily.map(d => d.cost),
                    borderColor: '#6366F1',
                    backgroundColor: 'rgba(99,102,241,0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 3
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: isDark ? '#2D2D3D' : '#F3F4F6' }, ticks: { color: isDark ? '#9CA3AF' : '#6B7280', font: { size: 11 } } },
                    y: { grid: { color: isDark ? '#2D2D3D' : '#F3F4F6' }, ticks: { color: isDark ? '#9CA3AF' : '#6B7280', font: { size: 11 }, callback: v => '$' + v.toFixed(3) } }
                }
            }
        });
    },

    renderModelsChart(models) {
        const canvas = $('models-chart');
        if (!canvas) return;
        new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: models.map(m => m.model),
                datasets: [{
                    data: models.map(m => m.cost),
                    backgroundColor: ['#6366F1', '#8B5CF6', '#10B981', '#F59E0B', '#EF4444']
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'right', labels: { font: { size: 12 }, color: state.theme === 'dark' ? '#E5E7EB' : '#111827' } }
                }
            }
        });
    },

    showCreateUser() {
        // BUG-10 FIX: HTML uses id=create-user-modal, edit-user-id, user-form-*, user-form-pass-group
        const modal = $('create-user-modal');
        if (!modal) return;
        const titleEl = $('user-modal-title');
        if (titleEl) titleEl.textContent = 'Создать пользователя';
        const form = $('user-form');
        if (form) form.reset();
        const idEl = $('edit-user-id');
        if (idEl) idEl.value = '';
        const passGroup = $('user-form-pass-group');
        if (passGroup) passGroup.style.display = '';
        modal.classList.remove('hidden');
    },

    showEditUser(userId) {
        // BUG-10 FIX: correct HTML IDs
        const user = state.adminData.users.find(u => u.id === userId);
        if (!user) return;
        const modal = $('create-user-modal');
        if (!modal) return;
        const titleEl = $('user-modal-title');
        if (titleEl) titleEl.textContent = 'Редактировать пользователя';
        const idEl = $('edit-user-id');
        if (idEl) idEl.value = userId;
        const loginEl = $('user-form-login');
        if (loginEl) loginEl.value = user.username || user.email || '';
        const nameEl = $('user-form-name');
        if (nameEl) nameEl.value = user.full_name || user.name || '';
        const roleEl = $('user-form-role');
        if (roleEl) roleEl.value = user.role;
        const limitEl = $('user-form-limit');
        if (limitEl) limitEl.value = user.monthly_limit || 2;
        const passGroup = $('user-form-pass-group');
        if (passGroup) passGroup.style.display = 'none';
        modal.classList.remove('hidden');
    },

    async saveUser(e) {
        e.preventDefault();
        // BUG-10 FIX: correct HTML IDs for user form
        const userId = ($('edit-user-id') || {}).value || '';
        const loginVal = ($('user-form-login') || {}).value?.trim() || '';
        const data = {
            email: loginVal,
            username: loginVal,
            name: ($('user-form-name') || {}).value?.trim() || '',
            full_name: ($('user-form-name') || {}).value?.trim() || '',
            role: ($('user-form-role') || {}).value || 'user',
            monthly_limit: parseFloat(($('user-form-limit') || {}).value) || 2
        };
        const password = ($('user-form-password') || {}).value || '';
        if (password) data.password = password;

        try {
            if (userId) {
                await API.put('/admin/users/' + userId, data);
                Toast.show('Пользователь обновлён', 'success');
            } else {
                if (!data.password) { Toast.show('Введите пароль', 'error'); return; }
                await API.post('/admin/users', data);
                Toast.show('Пользователь создан', 'success');
            }
            ($('user-modal') || $('create-user-modal')).classList.add('hidden');
            await this.loadUsers();
        } catch (err) {
            Toast.show('Ошибка: ' + err.message, 'error');
        }
    },

    async toggleBlock(userId, isBlocked) {
        try {
            await API.put('/admin/users/' + userId, { is_blocked: !isBlocked });
            Toast.show(isBlocked ? 'Пользователь разблокирован' : 'Пользователь заблокирован', 'success');
            await this.loadUsers();
        } catch (err) {
            Toast.show('Ошибка: ' + err.message, 'error');
        }
    }
};

/* ── INIT ─────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // CHIP EVENT DELEGATION FIX
  document.addEventListener('click', function(e) {
    const chip = e.target.closest('.welcome-chip[data-prompt]');
    if (chip) {
      e.preventDefault();
      e.stopPropagation();
      const prompt = chip.dataset.prompt;
      if (prompt && typeof Chat !== 'undefined' && Chat.sendFromChip) {
        Chat.sendFromChip(prompt);
      }
    }
  });

    Theme.init();

    // Bind auth form BEFORE Auth.init so login works on first load
    const authForm = $('auth-form');
    if (authForm) authForm.addEventListener('submit', e => Auth.handleLogin(e));

    Auth.init();

    // Admin modal tabs
    $$('.modal-tab[data-tab]').forEach(tab => {
        tab.addEventListener('click', () => {
            const panel = tab.closest('.modal');
            if (panel && panel.id === 'admin-modal') {
                AdminPanel.loadTab(tab.dataset.tab);
            }
        });
    });

    // Admin modal close (BUG-8 FIX: HTML uses id=btn-admin-close)
    const adminClose = $('btn-admin-close');
    if (adminClose) adminClose.addEventListener('click', () => AdminPanel.close());

    // Admin modal overlay click
    const adminModal = $('admin-modal');
    if (adminModal) {
        adminModal.addEventListener('click', e => {
            if (e.target === adminModal) AdminPanel.close();
        });
    }

    // User form
    const userForm = $('user-form');
    if (userForm) userForm.addEventListener('submit', e => AdminPanel.saveUser(e));

    // User modal close (BUG-10 FIX: correct IDs)
    const userModalClose = $('btn-user-modal-close');
    if (userModalClose) userModalClose.addEventListener('click', () => $('create-user-modal').classList.add('hidden'));

    // User modal cancel
    const userCancel = $('btn-user-cancel');
    if (userCancel) userCancel.addEventListener('click', () => $('create-user-modal').classList.add('hidden'));

    initResizable();

    MultiSSH.init();
    console.log('%cORION Digital v1.4', 'color:#6366F1;font-size:18px;font-weight:bold');
    console.log('%cReady. Auth:', 'color:#10B981', state.user ? 'logged in' : 'not logged in');
});

function initResizable() {
    document.querySelectorAll('.resize-handle').forEach(handle => {
        let startX, startWidth, target;
        handle.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const targetId = handle.dataset.target;
            target = document.getElementById(targetId);
            if (!target) return;
            startX = e.clientX;
            startWidth = target.offsetWidth;
            handle.classList.add('active');
            const onMouseMove = (e) => {
                const delta = targetId === 'activity-panel' ? startX - e.clientX : e.clientX - startX;
                const newWidth = Math.max(200, Math.min(600, startWidth + delta));
                target.style.width = newWidth + 'px';
                target.style.minWidth = newWidth + 'px';
            };
            const onMouseUp = () => {
                handle.classList.remove('active');
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
                localStorage.setItem('orion_' + targetId + '_width', target.style.width);
            };
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    });
    ['sidebar', 'activity-panel'].forEach(id => {
        const saved = localStorage.getItem('orion_' + id + '_width');
        const el = document.getElementById(id);
        if (saved && el) { el.style.width = saved; el.style.minWidth = saved; }
    });
}

const TaskPlan = {
    currentPlan: null,
    planEl: null,

    show(plan) {
        this.currentPlan = plan;

        // Если чат, не показываем план
        if (plan.mode === 'chat' || !plan.steps || plan.steps.length <= 1) return;

        // Создать элемент плана в чате
        const container = document.querySelector('.chat-messages, #chat-messages, .messages-list, #messages-container, .messages-container');
        if (!container) return;

        const el = document.createElement('div');
        el.className = 'task-plan-card';
        el.id = 'task-plan-current';

        // Заголовок
        let html = `
            <div class="plan-header">
                <span class="plan-icon">📋</span>
                <span class="plan-title">План выполнения</span>
                <span class="plan-mode">${this._modeLabel(plan.mode)}</span>
            </div>
        `;

        // Понимание задачи
        if (plan.understanding) {
            html += `<div class="plan-understanding">${this._escapeHtml(plan.understanding)}</div>`;
        }

        // Фазы
        html += '<div class="plan-phases">';
        (plan.steps || []).forEach((step, i) => {
            const agents = (step.agents || []).map(a => this._agentEmoji(a) + ' ' + this._agentName(a)).join(', ');
            const parallel = step.parallel ? ' <span class="plan-parallel">⚡ параллельно</span>' : '';
            html += `
                <div class="plan-phase" id="plan-phase-${i}" data-status="pending">
                    <div class="plan-phase-indicator">
                        <span class="plan-phase-dot"></span>
                        ${i < (plan.steps.length - 1) ? '<span class="plan-phase-line"></span>' : ''}
                    </div>
                    <div class="plan-phase-content">
                        <div class="plan-phase-name">${step.name}${parallel}</div>
                        <div class="plan-phase-agents">${agents}</div>
                        ${step.description ? `<div class="plan-phase-desc">${this._escapeHtml(step.description)}</div>` : ''}
                    </div>
                </div>
            `;
        });
        html += '</div>';

        // Предупреждения
        if (plan.warnings && plan.warnings.length) {
            html += '<div class="plan-warnings">';
            plan.warnings.forEach(w => {
                html += `<div class="plan-warning">⚠️ ${this._escapeHtml(w)}</div>`;
            });
            html += '</div>';
        }

        // Время
        if (plan.estimated_time) {
            html += `<div class="plan-time">⏱ Примерное время: ${plan.estimated_time}</div>`;
        }

        el.innerHTML = html;
        container.appendChild(el);
        this.planEl = el;

        // Автоскролл
        container.scrollTop = container.scrollHeight;
    },

    startPhase(index, name, agents) {
        const phaseEl = document.getElementById(`plan-phase-${index}`);
        if (phaseEl) {
            phaseEl.dataset.status = 'running';
            // Обновить все предыдущие как done (на случай пропуска)
            for (let i = 0; i < index; i++) {
                const prev = document.getElementById(`plan-phase-${i}`);
                if (prev && prev.dataset.status !== 'done') prev.dataset.status = 'done';
            }
        }
    },

    completePhase(index, success) {
        const phaseEl = document.getElementById(`plan-phase-${index}`);
        if (phaseEl) {
            phaseEl.dataset.status = success ? 'done' : 'error';
        }
    },

    // Helpers
    _modeLabel(mode) {
        const labels = {
            'single': '1 агент',
            'multi_sequential': 'Последовательно',
            'multi_parallel': 'Параллельно ⚡'
        };
        return labels[mode] || mode;
    },

    _agentEmoji(key) {
        const emojis = { designer: '🎨', developer: '💻', devops: '🔧', integrator: '🔌', tester: '🧪', analyst: '📊' };
        return emojis[key] || '⚡';
    },

    _agentName(key) {
        const names = { designer: 'Дизайнер', developer: 'Разработчик', devops: 'DevOps', integrator: 'Интегратор', tester: 'Тестировщик', analyst: 'Аналитик' };
        return names[key] || key;
    },

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};


// ═══════════════════════════════════════════════════════════════
// ЧАСТЬ 3: Модуль Ask User — агент спрашивает пользователя
// ═══════════════════════════════════════════════════════════════

const AskUser = {
    show(question) {
        // Показать вопрос в чате как специальное сообщение
        const container = document.querySelector('.chat-messages, #chat-messages, .messages-list, #messages-container, .messages-container');
        if (!container) return;

        const el = document.createElement('div');
        el.className = 'ask-user-card';
        el.innerHTML = `
            <div class="ask-user-header">
                <span class="ask-user-icon">🤔</span>
                <span>Агент задаёт вопрос</span>
            </div>
            <div class="ask-user-question">${this._escapeHtml(question)}</div>
            <div class="ask-user-input-wrap">
                <textarea class="ask-user-textarea" placeholder="Ваш ответ..." rows="2"></textarea>
                <div class="ask-user-actions">
                    <button class="btn-secondary ask-user-skip">Пропустить</button>
                    <button class="btn-primary ask-user-send">Ответить</button>
                </div>
            </div>
        `;

        container.appendChild(el);
        container.scrollTop = container.scrollHeight;

        // Фокус на textarea
        const textarea = el.querySelector('.ask-user-textarea');
        if (textarea) textarea.focus();

        // Обработчики
        el.querySelector('.ask-user-send').addEventListener('click', () => {
            const answer = textarea.value.trim();
            if (answer) {
                // Отправить ответ как обычное сообщение
                Chat.send(answer);
                el.remove();
            }
        });

        el.querySelector('.ask-user-skip').addEventListener('click', () => {
            Chat.send('[пропущено]');
            el.remove();
        });

        // Enter для отправки
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                el.querySelector('.ask-user-send').click();
            }
        });
    },

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};


// ═══════════════════════════════════════════════════════════════
// ═════════════════════════════════════════════════════════════
// ПАТЧ ЗАДАЧА-1: AuthForm — безопасная форма авторизации
// Когда агент встречает форму логина, он показывает скриншот и поля
// ввода прямо в чате ORION. Пароли не хранятся в чате.
// ═════════════════════════════════════════════════════════════

const AuthForm = {
    show(evt) {
        const container = document.querySelector('.chat-messages, #chat-messages, .messages-list, #messages-container, .messages-container');
        if (!container) return;

        const fields = evt.fields || [];
        const screenshotHtml = evt.screenshot
            ? `<div class="auth-screenshot"><img src="data:image/png;base64,${evt.screenshot}" alt="Страница авторизации" style="max-width:100%;border-radius:8px;border:1px solid var(--border-color);margin-bottom:12px;"></div>`
            : '';

        let fieldsHtml = '';
        fields.forEach(f => {
            const inputType = f.type === 'password' ? 'password' : 'text';
            const label = f.type === 'password' ? 'Пароль' : 'Логин';
            fieldsHtml += `
                <div class="auth-field">
                    <label class="auth-label">${label} (${f.name})</label>
                    <input type="${inputType}" class="auth-input form-input" 
                           data-field-name="${f.name}" data-selector="${f.selector || ''}"
                           placeholder="Введите ${label.toLowerCase()}...">
                </div>
            `;
        });

        // Если поля не обнаружены — показываем дефолтные
        if (fields.length === 0) {
            fieldsHtml = `
                <div class="auth-field">
                    <label class="auth-label">Логин</label>
                    <input type="text" class="auth-input form-input" data-field-name="login" placeholder="Введите логин...">
                </div>
                <div class="auth-field">
                    <label class="auth-label">Пароль</label>
                    <input type="password" class="auth-input form-input" data-field-name="password" placeholder="Введите пароль...">
                </div>
            `;
        }

        const card = document.createElement('div');
        card.className = 'auth-required-card';
        card.innerHTML = `
            <div class="auth-header">
                <span class="auth-icon">🔐</span>
                <span>Требуется авторизация</span>
            </div>
            <div class="auth-url">${evt.url || 'Страница входа'}</div>
            ${screenshotHtml}
            <div class="auth-hint">Введите данные для входа. Пароли не сохраняются в чате.</div>
            <div class="auth-fields">
                ${fieldsHtml}
            </div>
            <div class="auth-actions">
                <button class="btn-secondary auth-skip">Пропустить</button>
                <button class="btn-primary auth-submit">🔓 Войти</button>
            </div>
        `;

        container.appendChild(card);
        container.scrollTop = container.scrollHeight;

        // Фокус на первом поле
        const firstInput = card.querySelector('.auth-input');
        if (firstInput) firstInput.focus();

        // Обработчик отправки
        card.querySelector('.auth-submit').addEventListener('click', () => {
            const inputs = card.querySelectorAll('.auth-input');
            const authData = {};
            inputs.forEach(inp => {
                authData[inp.dataset.fieldName] = {
                    value: inp.value,
                    selector: inp.dataset.selector || ''
                };
            });
            // Отправляем данные агенту через API
            this._sendAuth(authData, evt.url);
            // Убираем карточку и показываем статус
            card.innerHTML = '<div class="auth-sent">🔐 Данные отправлены агенту. Выполняю вход...</div>';
            setTimeout(() => card.remove(), 5000);
        });

        // Пропуск
        card.querySelector('.auth-skip').addEventListener('click', () => {
            Chat.send('[auth_skipped]');
            card.remove();
        });

        // Enter для отправки
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                card.querySelector('.auth-submit').click();
            }
        });
    },

    async _sendAuth(authData, url) {
        try {
            const chatId = state.currentChatId;
            await API.post('/auth-response', {
                chat_id: chatId,
                auth_data: authData,
                url: url
            });
        } catch (err) {
            console.error('Auth response error:', err);
            // Fallback: отправить как обычное сообщение (без паролей в тексте)
            Chat.send('[auth_provided] Данные отправлены');
        }
    }
};

// ЧАСТЬ 4: Multi-SSH — поддержка нескольких серверов
// Вставить в HTML настроек (settings modal)
// ═══════════════════════════════════════════════════════════════

const MultiSSH = {
    servers: [],

    init() {
        // Загрузить из localStorage
        try {
            this.servers = JSON.parse(localStorage.getItem('orion_ssh_servers') || '[]');
        } catch { this.servers = []; }
    },

    addServer(name, host, user, password, port) {
        this.servers.push({
            id: Date.now().toString(),
            name: name || host,
            host, user, password,
            port: port || 22,
            active: this.servers.length === 0  // Первый = активный
        });
        this.save();
    },

    removeServer(id) {
        this.servers = this.servers.filter(s => s.id !== id);
        this.save();
    },

    setActive(id) {
        this.servers.forEach(s => s.active = (s.id === id));
        this.save();
    },

    getActive() {
        return this.servers.find(s => s.active) || this.servers[0] || null;
    },

    getAll() {
        return this.servers;
    },

    save() {
        localStorage.setItem('orion_ssh_servers', JSON.stringify(this.servers));
    },

    // Для отправки с сообщением — активный сервер
    getCredentials() {
        const active = this.getActive();
        if (!active) return {};
        return {
            ssh_host: active.host,
            ssh_user: active.user,
            ssh_password: active.password,
            ssh_port: active.port
        };
    },

    // Рендер списка серверов в настройках
    renderInSettings(container) {
        let html = `
            <div class="ssh-servers-list">
                <div class="ssh-servers-header">
                    <h4>SSH Серверы</h4>
                    <button class="btn-sm btn-primary" onclick="MultiSSH.showAddForm()">+ Добавить</button>
                </div>
        `;

        if (this.servers.length === 0) {
            html += '<div class="ssh-empty">Нет серверов. Добавьте для деплоя и управления.</div>';
        } else {
            this.servers.forEach(s => {
                html += `
                    <div class="ssh-server-item ${s.active ? 'active' : ''}">
                        <div class="ssh-server-info">
                            <div class="ssh-server-name">${s.name}</div>
                            <div class="ssh-server-host">${s.user}@${s.host}:${s.port}</div>
                        </div>
                        <div class="ssh-server-actions">
                            ${!s.active ? `<button class="btn-xs" onclick="MultiSSH.setActive('${s.id}')">Активировать</button>` : '<span class="ssh-active-badge">Активный</span>'}
                            <button class="btn-xs btn-danger" onclick="MultiSSH.removeServer('${s.id}'); MultiSSH.renderInSettings(this.closest('.ssh-servers-list').parentElement)">✕</button>
                        </div>
                    </div>
                `;
            });
        }

        html += `
                <div class="ssh-add-form hidden" id="ssh-add-form">
                    <input type="text" placeholder="Название (мой сервер)" id="ssh-add-name" class="form-input">
                    <div style="display:flex;gap:8px">
                        <input type="text" placeholder="IP / хост" id="ssh-add-host" class="form-input" style="flex:2">
                        <input type="number" placeholder="22" id="ssh-add-port" class="form-input" style="flex:1" value="22">
                    </div>
                    <input type="text" placeholder="Пользователь (root)" id="ssh-add-user" class="form-input" value="root">
                    <input type="password" placeholder="Пароль" id="ssh-add-pass" class="form-input">
                    <div style="display:flex;gap:8px;justify-content:flex-end">
                        <button class="btn-secondary btn-sm" onclick="document.getElementById('ssh-add-form').classList.add('hidden')">Отмена</button>
                        <button class="btn-primary btn-sm" onclick="MultiSSH.saveFromForm()">Сохранить</button>
                    </div>
                </div>
            </div>
        `;

        container.innerHTML = html;
    },

    showAddForm() {
        const form = document.getElementById('ssh-add-form');
        if (form) form.classList.remove('hidden');
    },

    saveFromForm() {
        const name = document.getElementById('ssh-add-name').value;
        const host = document.getElementById('ssh-add-host').value;
        const port = document.getElementById('ssh-add-port').value;
        const user = document.getElementById('ssh-add-user').value;
        const pass = document.getElementById('ssh-add-pass').value;
        if (!host) return alert('Укажите хост');
        this.addServer(name, host, user || 'root', pass, parseInt(port) || 22);
        // Перерендерить
        const container = document.querySelector('.ssh-servers-list')?.parentElement;
        if (container) this.renderInSettings(container);
    }
};

/* ── GLOBAL HELPERS (called from HTML onclick) ─────────────── */
window.Chat = Chat;
window.ChatList = ChatList;
window.TaskPlan = TaskPlan;
window.AskUser = AskUser;
window.AuthForm = AuthForm;
window.MultiSSH = MultiSSH;
window.AdminPanel = AdminPanel;
window.Lightbox = Lightbox;
window.ActivityPanel = ActivityPanel;


// Request notification permission
if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
}
