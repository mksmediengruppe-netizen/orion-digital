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
    'pro-premium':   { label: 'Pro Премиум',    tag: 'ELITE', desc: 'Мультиагент: Designer + Developer + DevOps одновременно.' }
};

const WELCOME_CHIPS = [
    'Создай лендинг для SaaS продукта',
    'Разверни Docker контейнер на сервере',
    'Напиши Python скрипт для парсинга',
    'Настрой nginx с SSL сертификатом',
    'Сделай REST API на FastAPI',
    'Проанализируй логи и найди ошибки'
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
        if (!n) return '$0.000';
        return '$' + Number(n).toFixed(3);
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
        UI.init();
        ChatList.load();
        UI.updateUserInfo();
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
        // Default to light theme; only use saved if user explicitly set it
        const saved = localStorage.getItem('orion_theme');
        this.set(saved || 'light');
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
        this.renderModes();
        this.renderWelcome();
        this.bindEvents();
        Theme.init();
        ActivityPanel.hide();
    },

    renderModes() {
        const grid = document.querySelector('.modes-grid');
        if (!grid) return;
        grid.innerHTML = '';
        Object.entries(MODES).forEach(([key, m]) => {
            const btn = el('button', 'mode-btn' + (key === state.mode ? ' active' : ''));
            btn.dataset.mode = key;
            btn.innerHTML = `<span class="mode-name">${m.label}</span><span class="mode-tag">${m.tag}</span>`;
            btn.addEventListener('click', () => this.setMode(key));
            grid.appendChild(btn);
        });
        this.updateModeDesc();
    },

    setMode(key) {
        state.mode = key;
        $$('.mode-btn').forEach(b => b.classList.toggle('active', b.dataset.mode === key));
        this.updateModeDesc();
        this.updateFooterInfo();
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
                <div class="welcome-logo-icon">OR</div>
                <div class="welcome-title">ORION Digital</div>
                <div class="welcome-subtitle">AI-агент с полным доступом к серверу, браузеру и коду. Просто опишите задачу.</div>
            </div>
            <div class="welcome-chips">
                ${WELCOME_CHIPS.map(c => `<button class="welcome-chip" onclick="Chat.sendFromChip('${c.replace(/'/g, "\\'")}')">${c}</button>`).join('')}
            </div>
            <div class="welcome-models">
                ${MODEL_TAGS.map(m => `<div class="model-tag"><span class="model-tag-dot" style="background:${m.color}"></span>${m.name}</div>`).join('')}
            </div>`;
        msgs.appendChild(ws);
    },

    updateUserInfo() {
        const u = state.user;
        if (!u) return;
        const nameEl = document.querySelector('.user-name');
        const roleEl = document.querySelector('.user-role');
        const avatarEl = document.querySelector('.user-avatar');
        if (nameEl) nameEl.textContent = u.full_name || u.username;
        if (roleEl) roleEl.textContent = u.role === 'admin' ? 'Администратор' : 'Пользователь';
        if (avatarEl) avatarEl.textContent = (u.full_name || u.username || 'U')[0].toUpperCase();

        const adminBtn = $('btn-admin');
        if (adminBtn) adminBtn.style.display = u.role === 'admin' ? '' : 'none';

        this.updateCostBar();
    },

    updateCostBar() {
        const fill = document.querySelector('.cost-bar-fill');
        const val = document.querySelector('.cost-bar-value');
        if (!fill || !val) return;
        const pct = Math.min(100, (state.totalCost / state.monthlyLimit) * 100);
        fill.style.width = pct + '%';
        fill.className = 'cost-bar-fill' + (pct > 80 ? ' danger' : pct > 50 ? ' warn' : '');
        val.textContent = Utils.formatCost(state.totalCost) + ' / $' + state.monthlyLimit.toFixed(2);
    },

    updateFooterInfo() {
        const info = document.querySelector('.input-footer-info');
        if (info) {
            const mode = MODES[state.mode];
            info.textContent = `ORION Digital · ${mode?.label || ''} · ${Utils.formatCost(state.totalCost)} за чат`;
        }
    },

    updateChatTitle(title) {
        const inp = $('chat-title-input');
        if (inp) inp.value = title || 'Новый чат';
    },

    setStreaming(active) {
        state.isStreaming = active;
        const sendBtn = $('btn-send');
        const stopBtn = $('btn-stop');
        if (sendBtn) sendBtn.style.display = active ? 'none' : '';
        if (stopBtn) stopBtn.style.display = active ? '' : 'none';
        const textarea = $('message-input');
        if (textarea) textarea.placeholder = active ? 'Можно писать — сообщение встанет в очередь...' : 'Напишите сообщение...';
    },

    showQueueIndicator(count) {
        let qi = document.querySelector('.queue-indicator');
        if (count > 0) {
            if (!qi) {
                qi = el('div', 'queue-indicator');
                const inputArea = document.querySelector('.chat-input-area');
                if (inputArea) inputArea.insertBefore(qi, inputArea.firstChild);
            }
            qi.innerHTML = `⏳ В очереди: ${count} сообщение${count > 1 ? 'я' : ''}`;
        } else if (qi) {
            qi.remove();
        }
    },

    bindEvents() {
        // Auth form
        const authForm = $('auth-form');
        if (authForm) authForm.addEventListener('submit', e => Auth.handleLogin(e));

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
            textarea.addEventListener('input', () => this.autoResize(textarea));
        }

        // Send button
        const sendBtn = $('btn-send');
        if (sendBtn) sendBtn.addEventListener('click', () => Chat.send());

        // Stop button
        const stopBtn = $('btn-stop');
        if (stopBtn) stopBtn.addEventListener('click', () => Chat.stop());

        // Attach button
        const attachBtn = $('btn-attach');
        const fileInput = $('file-input');
        if (attachBtn && fileInput) {
            attachBtn.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', e => Attachments.handleFiles(e.target.files));
        }

        // Chat title rename
        const titleInput = $('chat-title-input');
        if (titleInput) {
            titleInput.addEventListener('blur', () => Chat.renameCurrentChat(titleInput.value));
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

        // Welcome chips (data-prompt buttons in HTML)
        document.querySelectorAll('[data-prompt]').forEach(btn => {
            btn.addEventListener('click', () => Chat.sendFromChip(btn.dataset.prompt));
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                Lightbox.close();
                AdminPanel.close();
                Sidebar.close();
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
            this.render();
        } catch (e) {
            console.warn('ChatList.load error:', e);
            state.chats = [];
            this.render();
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
        item.addEventListener('click', () => Chat.open(chat.id));
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
        if (!confirm('Удалить этот чат?')) return;
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
const Chat = {
    async newChat() {
        if (state.isStreaming) Chat.stop();
        state.currentChatId = null;
        state.messages = [];
        state.attachments = [];
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
        state.currentChatId = chatId;
        state.messages = [];
        ChatList.setActive(chatId);
        ActivityPanel.clear();
        Sidebar.close();

        const chat = state.chats.find(c => c.id === chatId);
        UI.updateChatTitle(chat?.title || 'Чат');

        try {
            const data = await API.get('/chats/' + chatId);
            // Backend returns {chat: {messages: [...], ...}}
            const chatData = data.chat || data;
            state.messages = chatData.messages || data.messages || [];
            this.renderMessages();
        } catch (e) {
            Toast.show('Ошибка загрузки чата', 'error');
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
        const container = $('messages-container');
        if (container) {
            container.scrollTo({ top: container.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
        }
    },

    async send() {
        const textarea = $('message-input');
        if (!textarea) return;
        const text = textarea.value.trim();
        if (!text && !state.attachments.length) return;

        if (state.isStreaming) {
            state.messageQueue.push({ text, attachments: [...state.attachments] });
            UI.showQueueIndicator(state.messageQueue.length);
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
                attachments: attachments.map(a => a.id || a.url).filter(Boolean)
            };

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

            // Process queue
            if (state.messageQueue.length > 0) {
                const next = state.messageQueue.shift();
                UI.showQueueIndicator(state.messageQueue.length);
                setTimeout(() => this._doSend(next.text, next.attachments), 300);
            }
        }
    },

    _handleSSE(evt, aiMsgEl, aiContent, startTime) {
        switch (evt.type) {
            case 'content':  // backend sends {type: 'content', text: '...'}
            case 'text':
            case 'delta':
                aiContent += evt.text || evt.content || evt.delta || '';
                Messages.updateStreamContent(aiMsgEl, aiContent);
                break;
            case 'done':  // backend sends {type: 'done'} instead of [DONE]
                break;
            case 'meta':  // backend sends metadata at start, ignore
                break;
            case 'thinking':
                ActivityPanel.addLine('thinking', '🤔', evt.content || evt.text || '');
                break;
            case 'tool_start':
                ActivityPanel.addLine('tool-start', this._toolEmoji(evt.tool), evt.tool + ': ' + (evt.args || ''));
                break;
            case 'tool_result':
                ActivityPanel.addLine('tool-result', '📄', evt.result || '', true);
                break;
            case 'code_write':
                ActivityPanel.addCodeBlock(evt.filename || 'file', evt.content || '');
                break;
            case 'browser_update':
                ActivityPanel.addScreenshot(evt.url || '', evt.screenshot || '', evt.status || '');
                break;
            case 'iteration':
                ActivityPanel.updateProgress(evt.current, evt.total, evt.steps);
                ActivityPanel.addLine('iteration', '🔄', `Итерация ${evt.current}/${evt.total}`);
                break;
            case 'artifact':
                Messages.addArtifact(aiMsgEl, evt);
                break;
            case 'followups':
                Messages.addFollowups(aiMsgEl, evt.suggestions || []);
                break;
            case 'task_complete':
                Messages.addTaskSummary(aiMsgEl, evt);
                ActivityPanel.setStatus('done');
                break;
            case 'human_handoff':
                ActivityPanel.showTakeover(evt.message || 'Агент нуждается в помощи', evt.screenshot || '');
                break;
            case 'error':
                ActivityPanel.addLine('error', '❌', evt.message || evt.error || 'Ошибка');
                break;
            case 'cost':
                state.totalCost += evt.amount || 0;
                UI.updateCostBar();
                UI.updateFooterInfo();
                if (state.currentChatId) ChatList.updateChatCost(state.currentChatId, evt.chat_total || state.totalCost);
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
            browser_check_api: '🌐', web_search: '🔍', web_fetch: '🔍',
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
            await API.put('/chats/' + chatId, { title });
            const chat = state.chats.find(c => c.id === chatId);
            if (chat) chat.title = title;
            ChatList.render();
        } catch (e) {
            console.warn('Rename error:', e);
        }
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
        const body = wrapper.querySelector('.msg-body');
        if (body) {
            body.appendChild(this.renderActions(content));
        }
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
            </div>`;
        return card;
    }
};

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
        if (log) log.innerHTML = '';
        state.activityLines = [];
        this.updateProgress(0, 0, []);
        this.hideTakeover();
    },

    setStatus(status) {
        const statusEl = document.querySelector('.activity-status');
        const pulseEl = document.querySelector('.status-pulse');
        if (!statusEl || !pulseEl) return;
        const labels = { running: 'Работает', done: 'Завершено', waiting: 'Ожидает' };
        statusEl.className = 'activity-status ' + status;
        pulseEl.className = 'status-pulse ' + (status === 'running' ? '' : status);
        statusEl.innerHTML = `<span class="status-pulse ${status === 'running' ? '' : status}"></span>${labels[status] || status}`;
    },

    addLine(type, emoji, text, collapsible = false) {
        const log = $('activity-log');
        if (!log) return;

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

        const fill = progressEl.querySelector('.progress-bar-fill');
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
        const container = document.querySelector('.toast-container');
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
        this.currentTab = tab;
        $$('.modal-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        $$('.modal-tab-content').forEach(c => c.classList.toggle('active', c.id === 'admin-tab-' + tab));

        switch (tab) {
            case 'users': await this.loadUsers(); break;
            case 'chats': await this.loadAllChats(); break;
            case 'analytics': await this.loadAnalytics(); break;
        }
    },

    async loadUsers() {
        const container = $('admin-tab-users');
        if (!container) return;
        container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

        try {
            const data = await API.get('/admin/users');
            state.adminData.users = data.users || data || [];
            this.renderUsers(state.adminData.users);
        } catch (e) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-desc">Ошибка: ${Utils.escapeHtml(e.message)}</div></div>`;
        }
    },

    renderUsers(users) {
        const container = $('admin-tab-users');
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
        const container = $('admin-tab-chats');
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
        const container = $('admin-tab-chats');
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
                            <tr data-user="${Utils.escapeHtml((c.username || '').toLowerCase())}">
                                <td style="font-size:12px;font-weight:500">${Utils.escapeHtml(c.username || '—')}</td>
                                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${Utils.escapeHtml(c.title || 'Без названия')}</td>
                                <td style="font-size:12px;color:var(--text-secondary)">${Utils.formatDate(c.created_at)}</td>
                                <td style="text-align:center">${c.message_count || 0}</td>
                                <td style="color:var(--success);font-weight:500">${Utils.formatCost(c.total_cost)}</td>
                                <td style="font-size:11px;color:var(--text-tertiary)">${Utils.escapeHtml(c.mode || '—')}</td>
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
        const container = $('admin-tab-analytics');
        if (!container) return;
        container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

        try {
            const data = await API.get('/admin/analytics');
            state.adminData.analytics = data;
            this.renderAnalytics(data);
        } catch (e) {
            container.innerHTML = `<div class="empty-state"><div class="empty-state-desc">Ошибка: ${Utils.escapeHtml(e.message)}</div></div>`;
        }
    },

    renderAnalytics(data) {
        const container = $('admin-tab-analytics');
        if (!container) return;

        container.innerHTML = `
            <div class="analytics-grid">
                <div class="analytics-card">
                    <div class="analytics-card-label">Сегодня</div>
                    <div class="analytics-card-value">${Utils.formatCost(data.today || 0)}</div>
                    <div class="analytics-card-sub">${data.today_requests || 0} запросов</div>
                </div>
                <div class="analytics-card">
                    <div class="analytics-card-label">Эта неделя</div>
                    <div class="analytics-card-value">${Utils.formatCost(data.week || 0)}</div>
                    <div class="analytics-card-sub">${data.week_requests || 0} запросов</div>
                </div>
                <div class="analytics-card">
                    <div class="analytics-card-label">Этот месяц</div>
                    <div class="analytics-card-value">${Utils.formatCost(data.month || 0)}</div>
                    <div class="analytics-card-sub">${data.month_requests || 0} запросов</div>
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
        const modal = $('user-modal');
        if (!modal) return;
        $('user-modal-title').textContent = 'Создать пользователя';
        $('user-form').reset();
        $('user-id').value = '';
        $('user-password-group').style.display = '';
        modal.classList.remove('hidden');
    },

    showEditUser(userId) {
        const user = state.adminData.users.find(u => u.id === userId);
        if (!user) return;
        const modal = $('user-modal');
        if (!modal) return;
        $('user-modal-title').textContent = 'Редактировать пользователя';
        $('user-id').value = userId;
        $('user-username').value = user.username;
        $('user-fullname').value = user.full_name || '';
        $('user-role').value = user.role;
        $('user-limit').value = user.monthly_limit || 2;
        $('user-password-group').style.display = 'none';
        modal.classList.remove('hidden');
    },

    async saveUser(e) {
        e.preventDefault();
        const userId = $('user-id').value;
        const data = {
            username: $('user-username').value.trim(),
            full_name: $('user-fullname').value.trim(),
            role: $('user-role').value,
            monthly_limit: parseFloat($('user-limit').value) || 2
        };
        const password = $('user-password').value;
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
            $('user-modal').classList.add('hidden');
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

    // Admin modal close
    const adminClose = document.querySelector('#admin-modal .modal-close');
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

    // User modal close
    const userModalClose = document.querySelector('#user-modal .modal-close');
    if (userModalClose) userModalClose.addEventListener('click', () => $('user-modal').classList.add('hidden'));

    // User modal cancel
    const userCancel = $('btn-user-cancel');
    if (userCancel) userCancel.addEventListener('click', () => $('user-modal').classList.add('hidden'));

    console.log('%cORION Digital v1.4', 'color:#6366F1;font-size:18px;font-weight:bold');
    console.log('%cReady. Auth:', 'color:#10B981', state.user ? 'logged in' : 'not logged in');
});

/* ── GLOBAL HELPERS (called from HTML onclick) ─────────────── */
window.Chat = Chat;
window.ChatList = ChatList;
window.AdminPanel = AdminPanel;
window.Lightbox = Lightbox;
window.ActivityPanel = ActivityPanel;
