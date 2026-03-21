/* ═══════════════════════════════════════════════════════════
   ORION DIGITAL — app.js v4.0
   Full compatibility with Orion backend API
═══════════════════════════════════════════════════════════ */

'use strict';

/* ── CONFIG ──────────────────────────────────────────────── */
const API_BASE = '/api';  // nginx proxies /api/ to backend :3510

const MODE_INFO = {
  turbo_standard:  { label: 'Turbo',         desc: 'MiniMax + MiMo · Быстро и дёшево · Лимит $3',                 limit: 3 },
  pro_standard:    { label: 'Pro Standard',  desc: 'Claude Sonnet · Профессиональное качество · Лимит $5',         limit: 5 },
  pro_premium:     { label: 'Pro Premium',   desc: 'Claude Sonnet + Opus · Максимальное качество · Лимит $5',      limit: 5 },
  architect:       { label: 'Architect',     desc: 'Claude Opus · Архитектурные решения · Лимит $15',              limit: 15 },
};

const TEMPLATES = [
  { icon: '⚡', name: 'FastAPI Backend',    desc: 'REST API с JWT, PostgreSQL, Docker',         prompt: 'Создай FastAPI backend с JWT авторизацией, PostgreSQL и Docker. Задеплой на сервер.' },
  { icon: '🐳', name: 'Docker + Nginx',     desc: 'Контейнеризация с reverse proxy и SSL',      prompt: 'Настрой Docker Compose с nginx reverse proxy и SSL сертификатом Let\'s Encrypt.' },
  { icon: '🤖', name: 'Telegram Bot',       desc: 'Бот с командами и базой данных',             prompt: 'Создай Telegram бота с командами, инлайн-кнопками и SQLite базой данных.' },
  { icon: '🌐', name: 'Лендинг',            desc: 'Современный адаптивный сайт',                prompt: 'Создай современный лендинг с адаптивным дизайном, анимациями и задеплой на сервер.' },
  { icon: '📊', name: 'Парсер данных',      desc: 'Скрапинг и обработка данных',                prompt: 'Напиши Python парсер для сбора данных с сайта, сохрани в CSV и базу данных.' },
  { icon: '🔐', name: 'VPN сервер',         desc: 'WireGuard VPN на сервере',                   prompt: 'Установи и настрой WireGuard VPN сервер, создай конфиги для клиентов.' },
  { icon: '📱', name: 'React App',          desc: 'Современное SPA приложение',                 prompt: 'Создай React приложение с TypeScript, TailwindCSS и задеплой на сервер.' },
  { icon: '🗄️', name: 'База данных',        desc: 'PostgreSQL с бэкапами и мониторингом',       prompt: 'Настрой PostgreSQL с автоматическими бэкапами, мониторингом и оптимизацией.' },
  { icon: '🔍', name: 'Аудит сервера',      desc: 'Полная проверка состояния системы',          prompt: 'Проведи полный аудит сервера: проверь логи, сервисы, безопасность и производительность.' },
  { icon: '🐍', name: 'Python скрипт',      desc: 'Автоматизация задач',                        prompt: 'Напиши Python скрипт для автоматизации задачи. Опиши что нужно автоматизировать.' },
  { icon: '📧', name: 'Email сервис',       desc: 'SMTP сервер и рассылки',                     prompt: 'Настрой email сервер Postfix с DKIM, SPF и создай систему рассылок.' },
  { icon: '🎯', name: 'CI/CD Pipeline',     desc: 'Автодеплой через GitHub Actions',            prompt: 'Настрой CI/CD pipeline с GitHub Actions для автоматического деплоя на сервер.' },
];

/* ── UTILS ───────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt = d => {
  const now = new Date(), dt = new Date(d);
  const diff = now - dt;
  if (diff < 60000) return 'только что';
  if (diff < 3600000) return Math.floor(diff/60000) + ' мин';
  if (diff < 86400000) return Math.floor(diff/3600000) + ' ч';
  return dt.toLocaleDateString('ru', {day:'numeric', month:'short'});
};

/* ── STATE ───────────────────────────────────────────────── */
const state = {
  token: localStorage.getItem('orion_token') || '',
  user: null,
  currentChatId: null,
  chats: [],
  messages: [],
  isStreaming: false,
  abortController: null,
  streamingMsgEl: null,
  streamingContent: '',
  streamingThinking: '',
  totalCost: 0,
  sessionCost: 0,
  mode: localStorage.getItem('orion_mode') || 'pro_standard',
  qaEnabled: false,
  attachments: [],
  ctxChatId: null,
  sidebarCollapsed: false,
  activityCollapsed: true,
  theme: localStorage.getItem('orion_theme') || 'dark',
};

/* ── API ─────────────────────────────────────────────────── */
const API = {
  async req(method, path, body) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (state.token) opts.headers['Authorization'] = 'Bearer ' + state.token;
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(API_BASE + path, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || err.message || res.statusText);
    }
    return res.json();
  },
  get: (p) => API.req('GET', p),
  post: (p, b) => API.req('POST', p, b),
  put: (p, b) => API.req('PUT', p, b),
  delete: (p) => API.req('DELETE', p),
};

/* ── TOAST ───────────────────────────────────────────────── */
const Toast = {
  show(msg, type = 'info', dur = 3500) {
    const c = $('toast-container');
    const t = el('div', 'toast ' + type);
    const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
    t.innerHTML = `<span style="font-size:14px">${icons[type]||'ℹ'}</span><span>${esc(msg)}</span>`;
    c.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateX(20px)'; t.style.transition = 'all .3s'; setTimeout(() => t.remove(), 300); }, dur);
  },
  success: (m) => Toast.show(m, 'success'),
  error: (m) => Toast.show(m, 'error'),
  warning: (m) => Toast.show(m, 'warning'),
  info: (m) => Toast.show(m, 'info'),
};

/* ── THEME ───────────────────────────────────────────────── */
const Theme = {
  init() {
    document.documentElement.setAttribute('data-theme', state.theme);
    this.updateIcons();
    const toggle = $('theme-toggle');
    if (toggle) {
      if (state.theme === 'light') toggle.classList.add('on');
      toggle.addEventListener('click', () => this.toggle());
    }
  },
  toggle() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('orion_theme', state.theme);
    document.documentElement.setAttribute('data-theme', state.theme);
    this.updateIcons();
    const toggle = $('theme-toggle');
    if (toggle) toggle.classList.toggle('on', state.theme === 'light');
  },
  updateIcons() {
    const sun = $('theme-icon-sun'), moon = $('theme-icon-moon');
    if (!sun || !moon) return;
    if (state.theme === 'dark') { sun.classList.remove('hidden'); moon.classList.add('hidden'); }
    else { sun.classList.add('hidden'); moon.classList.remove('hidden'); }
  }
};

/* ── AUTH ────────────────────────────────────────────────── */
const Auth = {
  async init() {
    // Bind auth form events immediately (before token check)
    this.bindAuthEvents();
    if (state.token) {
      try {
        const me = await API.get('/auth/me');
        state.user = me;
        this.onLogin();
        return;
      } catch { state.token = ''; localStorage.removeItem('orion_token'); }
    }
    this.showAuth();
  },
  bindAuthEvents() {
    const form = $('auth-form');
    if (form && !form._bound) {
      form._bound = true;
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await Auth.login($('auth-login').value, $('auth-password').value);
      });
      const togglePw = $('toggle-pw');
      if (togglePw) {
        togglePw.addEventListener('click', () => {
          const pw = $('auth-password');
          pw.type = pw.type === 'password' ? 'text' : 'password';
        });
      }
    }
  },
  showAuth() {
    $('auth-screen').classList.remove('hidden');
    $('app').classList.add('hidden');
  },
  onLogin() {
    $('auth-screen').classList.add('hidden');
    $('app').classList.remove('hidden');
    this.updateUserUI();
    App.init();
  },
  updateUserUI() {
    const u = state.user;
    if (!u) return;
    const name = u.username || u.login || 'Пользователь';
    $('sb-user-name').textContent = name;
    $('sb-user-role').textContent = u.role === 'admin' ? 'Администратор' : 'Пользователь';
    $('sb-user-avatar').textContent = name[0].toUpperCase();
    if (u.role === 'admin') $('btn-admin').classList.remove('hidden');
  },
  async login(login, password) {
    const btn = $('auth-submit');
    const spinner = btn.querySelector('.btn-spinner');
    const text = btn.querySelector('.btn-text');
    btn.disabled = true; spinner.classList.remove('hidden'); text.classList.add('hidden');
    try {
      const data = await API.post('/auth/login', { email: login, password });
      state.token = data.token || data.access_token;
      localStorage.setItem('orion_token', state.token);
      const me = await API.get('/auth/me');
      state.user = me;
      this.onLogin();
    } catch (e) {
      const errEl = $('auth-error');
      errEl.textContent = e.message || 'Неверный логин или пароль';
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false; spinner.classList.add('hidden'); text.classList.remove('hidden');
    }
  },
  logout() {
    state.token = ''; localStorage.removeItem('orion_token');
    state.user = null; state.currentChatId = null; state.chats = [];
    this.showAuth();
  }
};

/* ── CHAT LIST ───────────────────────────────────────────── */
const ChatList = {
  async load() {
    try {
      const data = await API.get('/chats');
      state.chats = data.chats || data || [];
      this.render();
    } catch (e) { console.warn('Load chats:', e); }
  },
  render(filter = '') {
    const list = $('chat-list');
    const chats = filter
      ? state.chats.filter(c => (c.title||'').toLowerCase().includes(filter.toLowerCase()))
      : state.chats;
    if (!chats.length) {
      list.innerHTML = '<div class="chat-list-empty">Нет чатов</div>';
      return;
    }
    // Group by date
    const today = new Date(); today.setHours(0,0,0,0);
    const yesterday = new Date(today); yesterday.setDate(yesterday.getDate()-1);
    const groups = { 'Сегодня': [], 'Вчера': [], 'Ранее': [] };
    chats.forEach(c => {
      const d = new Date(c.updated_at || c.created_at || Date.now());
      d.setHours(0,0,0,0);
      if (d >= today) groups['Сегодня'].push(c);
      else if (d >= yesterday) groups['Вчера'].push(c);
      else groups['Ранее'].push(c);
    });
    list.innerHTML = '';
    Object.entries(groups).forEach(([label, items]) => {
      if (!items.length) return;
      const gl = el('div', 'chats-group-label', label);
      list.appendChild(gl);
      items.forEach(c => list.appendChild(this.renderItem(c)));
    });
  },
  renderItem(chat) {
    const item = el('div', 'chat-item' + (chat.id === state.currentChatId ? ' active' : ''));
    item.dataset.chatId = chat.id;
    const icon = el('span', 'chat-item-icon', '💬');
    const text = el('div', 'chat-item-text', chat.title || 'Без названия');
    const time = el('span', 'chat-item-time', fmt(chat.updated_at || chat.created_at));
    const del = el('button', 'chat-item-del', '×');
    del.title = 'Удалить';
    item.append(icon, text, time, del);
    item.addEventListener('click', (e) => {
      if (e.target === del) return;
      Chat.load(chat.id);
    });
    item.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      CtxMenu.show(e, chat.id);
    });
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      Chat.delete(chat.id);
    });
    return item;
  },
  setActive(chatId) {
    document.querySelectorAll('.chat-item').forEach(i => {
      i.classList.toggle('active', i.dataset.chatId == chatId);
    });
  }
};

/* ── MESSAGES ────────────────────────────────────────────── */
const Messages = {
  renderUser(msg) {
    const wrap = el('div', 'msg-user');
    const avatar = el('div', 'msg-avatar');
    avatar.textContent = state.user?.username?.[0]?.toUpperCase() || 'U';
    const bubble = el('div', 'msg-bubble');
    bubble.textContent = msg.content;
    if (msg.attachments?.length) {
      const aw = el('div', 'msg-attachments');
      msg.attachments.forEach(a => {
        const ac = el('div', 'attachment-chip', '📎 ' + (a.name || a));
        aw.appendChild(ac);
      });
      bubble.appendChild(aw);
    }
    wrap.append(bubble, avatar);
    return wrap;
  },
  renderAgent(msg) {
    const wrap = el('div', 'msg-agent');
    const avatar = el('div', 'msg-avatar', '◎');
    const content = el('div', 'msg-content');
    const header = el('div', 'msg-agent-header');
    const name = el('span', 'msg-agent-name', 'ORION');
    const time = el('span', 'msg-agent-time', fmt(msg.created_at || Date.now()));
    header.append(name, time);
    const md = el('div', 'msg-md');
    md.innerHTML = this.md(msg.content || '');
    this.addCopyBtns(md);
    const actions = this.renderActions(msg.content);
    content.append(header, md, actions);
    wrap.append(avatar, content);
    return wrap;
  },
  renderStreaming() {
    const wrap = el('div', 'msg-agent');
    wrap.id = 'streaming-msg';
    const avatar = el('div', 'msg-avatar', '◎');
    const content = el('div', 'msg-content');
    const header = el('div', 'msg-agent-header');
    const name = el('span', 'msg-agent-name', 'ORION');
    const time = el('span', 'msg-agent-time', 'сейчас');
    header.append(name, time);
    const md = el('div', 'msg-md');
    md.innerHTML = '<span class="thinking-indicator"><span></span><span></span><span></span></span>';
    content.append(header, md);
    wrap.append(avatar, content);
    return wrap;
  },
  updateStreaming(text) {
    const msgEl = $('streaming-msg');
    if (!msgEl) return;
    const md = msgEl.querySelector('.msg-md');
    if (!md) return;
    md.innerHTML = this.md(text);
    this.addCopyBtns(md);
  },
  finalizeStreaming() {
    const msgEl = $('streaming-msg');
    if (!msgEl) return;
    msgEl.id = '';
    const md = msgEl.querySelector('.msg-md');
    if (md) {
      const actions = this.renderActions(state.streamingContent);
      msgEl.querySelector('.msg-content')?.appendChild(actions);
    }
  },
  renderActions(content) {
    const wrap = el('div', 'msg-actions');
    const copyBtn = el('button', 'msg-action-btn');
    copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Копировать';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(content || '').then(() => Toast.success('Скопировано'));
    });
    const regenBtn = el('button', 'msg-action-btn');
    regenBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> Повторить';
    regenBtn.addEventListener('click', () => Chat.regenerate());
    wrap.append(copyBtn, regenBtn);
    return wrap;
  },
  addCopyBtns(container) {
    container.querySelectorAll('pre').forEach(pre => {
      if (pre.querySelector('.copy-btn')) return;
      const btn = el('button', 'copy-btn', 'Копировать');
      btn.addEventListener('click', () => {
        navigator.clipboard.writeText(pre.textContent).then(() => { btn.textContent = 'Скопировано!'; setTimeout(() => btn.textContent = 'Копировать', 2000); });
      });
      pre.style.position = 'relative';
      pre.appendChild(btn);
    });
  },
  scrollToBottom() {
    const wrap = $('messages-wrap');
    if (wrap) wrap.scrollTop = wrap.scrollHeight;
  },
  md(text) {
    if (!text) return '';
    let html = esc(text);
    // Code blocks
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code class="lang-${lang||'text'}">${code.trim()}</code></pre>`
    );
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    // Blockquote
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
    // Horizontal rule
    html = html.replace(/^---$/gm, '<hr>');
    // Lists
    html = html.replace(/^(\s*)[*-] (.+)$/gm, '$1<li>$2</li>');
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');
    html = html.replace(/<\/ul>\s*<ul>/g, '');
    // Numbered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // Line breaks
    html = html.replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>');
    if (!html.startsWith('<')) html = '<p>' + html + '</p>';
    return html;
  }
};

/* ── ACTIVITY PANEL ──────────────────────────────────────── */
const Activity = {
  iteration: 0,
  maxIter: 0,
  phases: [],
  currentPhase: null,

  open() {
    const panel = $('activity-panel');
    panel.classList.remove('collapsed');
    state.activityCollapsed = false;
    $('activity-dot').classList.remove('hidden');
    const collapseBtn = $('btn-collapse-act');
    if (collapseBtn) {
      const svg = collapseBtn.querySelector('svg');
      if (svg) svg.style.transform = 'rotate(180deg)';
    }
  },
  close() {
    $('activity-panel').classList.add('collapsed');
    state.activityCollapsed = true;
    $('activity-dot').classList.add('hidden');
    const collapseBtn = $('btn-collapse-act');
    if (collapseBtn) {
      const svg = collapseBtn.querySelector('svg');
      if (svg) svg.style.transform = '';
    }
  },
  toggle() {
    if (state.activityCollapsed) this.open(); else this.close();
  },
  setStatus(status, text, agentName) {
    const dot = $('status-dot');
    const txt = $('status-text');
    const name = $('act-agent-name');
    if (dot) { dot.className = 'status-dot ' + status; }
    if (txt) txt.textContent = text;
    if (name && agentName) name.textContent = agentName;
  },
  setProgress(iter, max) {
    this.iteration = iter; this.maxIter = max;
    const label = $('progress-label');
    const fill = $('progress-fill');
    if (label) label.textContent = `Итерация ${iter} / ${max || '?'}`;
    if (fill) fill.style.width = max ? Math.min(100, (iter/max)*100) + '%' : '0%';
  },
  addPhase(name, status = 'pending') {
    const list = $('phase-list');
    if (!list) return;
    const existing = list.querySelector(`[data-phase="${esc(name)}"]`);
    if (existing) {
      existing.className = 'phase-item ' + status;
      return;
    }
    const item = el('div', 'phase-item ' + status);
    item.dataset.phase = name;
    const dot = el('div', 'phase-dot');
    const nm = el('span', 'phase-name', name);
    item.append(dot, nm);
    list.appendChild(item);
  },
  updatePhase(name, status) {
    const list = $('phase-list');
    if (!list) return;
    const item = list.querySelector(`[data-phase="${esc(name)}"]`);
    if (item) item.className = 'phase-item ' + status;
  },
  log(icon, iconClass, text, code, elapsed) {
    const log = $('act-log');
    if (!log) return;
    const item = el('div', 'act-item');
    const ic = el('div', 'act-icon ' + (iconClass||''));
    ic.textContent = icon;
    const txt = el('div', 'act-text', text);
    if (code) {
      const cd = el('code', '', code);
      txt.appendChild(cd);
    }
    item.append(ic, txt);
    if (elapsed) {
      const el2 = el('span', 'act-elapsed', elapsed);
      item.appendChild(el2);
    }
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
  },
  logThink(text) {
    const log = $('act-log');
    if (!log || !text) return;
    const item = el('div', 'act-think', text.substring(0, 200) + (text.length > 200 ? '...' : ''));
    log.appendChild(item);
    log.scrollTop = log.scrollHeight;
  },
  addTool(name, input, status = 'running') {
    const log = $('act-log');
    if (!log) return;
    const chip = el('div', 'act-tool-chip' + (status === 'done' ? ' act-tool-done' : status === 'error' ? ' act-tool-error' : ''));
    chip.id = 'tool-' + name.replace(/\W/g,'_') + '_' + Date.now();
    const icons = { bash: '💻', browser: '🌐', file: '📄', write_file: '✍️', read_file: '📖', memory: '🧠', search: '🔍', default: '⚙️' };
    const icon = icons[name.toLowerCase()] || icons.default;
    const ic = el('div', 'act-icon agent', icon);
    const info = el('div', 'act-text');
    const nm = el('strong', '', name);
    info.appendChild(nm);
    if (input) {
      const inp = el('code', '', typeof input === 'string' ? input.substring(0, 80) : JSON.stringify(input).substring(0, 80));
      info.appendChild(inp);
    }
    if (status === 'running') {
      const dot = el('span', 'act-active-dot');
      chip.appendChild(dot);
    }
    chip.append(ic, info);
    log.appendChild(chip);
    log.scrollTop = log.scrollHeight;
    return chip.id;
  },
  updateTool(id, status, output) {
    const chip = document.getElementById(id);
    if (!chip) return;
    chip.className = 'act-tool-chip ' + (status === 'done' ? 'act-tool-done' : status === 'error' ? 'act-tool-error' : '');
    const dot = chip.querySelector('.act-active-dot');
    if (dot) dot.remove();
    if (output) {
      const out = el('code', '', output.substring(0, 100));
      chip.querySelector('.act-text')?.appendChild(out);
    }
  },
  showTakeover(desc) {
    const panel = $('takeover-panel');
    if (!panel) return;
    $('takeover-desc').textContent = desc;
    panel.classList.remove('hidden');
    $('takeover-input').focus();
    this.open();
  },
  hideTakeover() {
    const panel = $('takeover-panel');
    if (panel) panel.classList.add('hidden');
  },
  clear() {
    const log = $('act-log');
    if (log) log.innerHTML = '';
    const phases = $('phase-list');
    if (phases) phases.innerHTML = '';
    this.setProgress(0, 0);
    this.setStatus('idle', 'Ожидает');
  },
  addScreenshot(url) {
    const log = $('act-log');
    if (!log || !url) return;
    const wrap = el('div', 'act-screenshot');
    const img = el('img');
    img.src = url; img.alt = 'Screenshot';
    wrap.appendChild(img);
    log.appendChild(wrap);
    log.scrollTop = log.scrollHeight;
  }
};

/* ── PIPELINE ────────────────────────────────────────────── */
const Pipeline = {
  phases: [],
  show(phases) {
    this.phases = phases;
    const el2 = $('pipeline');
    const inner = $('pipeline-inner');
    if (!el2 || !inner) return;
    inner.innerHTML = '';
    phases.forEach((ph, i) => {
      if (i > 0) inner.appendChild(el('span', 'ph-arrow', '›'));
      const item = el('div', 'ph ph-pending');
      item.id = 'ph-' + i;
      item.textContent = ph;
      inner.appendChild(item);
    });
    el2.classList.remove('hidden'); el2.classList.add('visible');
  },
  setActive(idx) {
    this.phases.forEach((_, i) => {
      const item = $('ph-' + i);
      if (!item) return;
      if (i < idx) item.className = 'ph ph-done';
      else if (i === idx) item.className = 'ph ph-active';
      else item.className = 'ph ph-pending';
    });
  },
  hide() {
    const el2 = $('pipeline');
    if (el2) { el2.classList.add('hidden'); el2.classList.remove('visible'); }
  }
};

/* ── SSE HANDLER ─────────────────────────────────────────── */
const SSE = {
  toolMap: {},

  handle(type, data) {
    switch (type) {
      // ── Text content ──
      case 'content':
      case 'text':
      case 'delta':
      case 'text_delta': {
        const chunk = data.content || data.text || data.delta || data.chunk || '';
        state.streamingContent += chunk;
        Messages.updateStreaming(state.streamingContent);
        Messages.scrollToBottom();
        break;
      }
      // ── Thinking ──
      case 'thinking':
      case 'thinking_text': {
        const think = data.thinking || data.text || '';
        state.streamingThinking += think;
        Activity.logThink(think);
        break;
      }
      // ── Tool use ──
      case 'tool_use':
      case 'tool_call': {
        const name = data.name || data.tool_name || 'tool';
        const input = data.input || data.args || data.parameters || {};
        const id = Activity.addTool(name, typeof input === 'string' ? input : (input.command || input.url || input.query || JSON.stringify(input)).substring(0, 80));
        this.toolMap[data.id || name] = id;
        Activity.setStatus('running', 'Выполняет: ' + name);
        $('intent-badge').textContent = '🔧 ' + name;
        break;
      }
      // ── Tool result ──
      case 'tool_result':
      case 'tool_response': {
        const toolId = data.tool_use_id || data.id || '';
        const chipId = this.toolMap[toolId];
        const output = data.output || data.result || data.content || '';
        const isError = data.is_error || data.error || false;
        if (chipId) Activity.updateTool(chipId, isError ? 'error' : 'done', typeof output === 'string' ? output : JSON.stringify(output).substring(0, 100));
        // Log SSH/browser output
        if (data.tool_name === 'bash' || data.tool_name === 'ssh') {
          Activity.log('💻', 'ssh', 'Команда выполнена', typeof output === 'string' ? output.substring(0, 100) : '');
        } else if (data.tool_name === 'browser') {
          Activity.log('🌐', 'browser', 'Браузер', typeof output === 'string' ? output.substring(0, 80) : '');
        }
        // Screenshot
        if (data.screenshot) Activity.addScreenshot(data.screenshot);
        break;
      }
      // ── Cost ──
      case 'cost': {
        const cost = data.cost || data.total_cost || 0;
        state.totalCost = cost;
        state.sessionCost = cost;
        Budget.update(cost);
        break;
      }
      // ── Title ──
      case 'title': {
        const title = data.title || '';
        if (title) {
          $('chat-title').textContent = title;
          const chat = state.chats.find(c => c.id === state.currentChatId);
          if (chat) { chat.title = title; ChatList.render(); }
        }
        break;
      }
      // ── Task steps / phases ──
      case 'task_steps':
      case 'plan': {
        const steps = data.steps || data.phases || data.plan || [];
        if (steps.length) {
          Pipeline.show(steps);
          steps.forEach(s => Activity.addPhase(s, 'pending'));
        }
        break;
      }
      case 'step_start':
      case 'phase_start': {
        const name = data.step || data.phase || data.name || '';
        Activity.updatePhase(name, 'running');
        Activity.setStatus('running', name);
        break;
      }
      case 'step_done':
      case 'phase_done': {
        const name = data.step || data.phase || data.name || '';
        Activity.updatePhase(name, 'done');
        break;
      }
      // ── Iteration ──
      case 'iteration':
      case 'loop': {
        const iter = data.iteration || data.loop || 0;
        const max = data.max_iterations || data.max || 0;
        Activity.setProgress(iter, max);
        break;
      }
      // ── Agent info ──
      case 'agent_start': {
        const name = data.agent || data.name || 'Агент';
        Activity.setStatus('running', 'Работает', name);
        Activity.open();
        $('activity-dot').classList.remove('hidden');
        break;
      }
      case 'agent_done': {
        Activity.setStatus('done', 'Завершён');
        $('activity-dot').classList.add('hidden');
        break;
      }
      // ── Human handoff ──
      case 'human_handoff':
      case 'human_input_required': {
        const desc = data.description || data.message || 'Агент ждёт вашего ответа';
        Activity.showTakeover(desc);
        Activity.setStatus('idle', 'Ожидает ответа');
        break;
      }
      // ── Memory ──
      case 'memory_saved':
      case 'memory': {
        Activity.log('🧠', 'think', 'Память сохранена: ' + (data.summary || data.content || '').substring(0, 60));
        break;
      }
      // ── PATCH 14: Interrupt / Queue / Append notifications ──
      case 'queued': {
        const qtext = data.text || '🕐 В очереди';
        UI.showInterruptBadge('queue', qtext);
        Activity.log('🕐', 'think', qtext);
        break;
      }
      case 'appended': {
        const atext = data.text || '📩 Добавлено к задаче';
        UI.showInterruptBadge('append', atext);
        Activity.log('📩', 'think', atext);
        break;
      }
      case 'interrupted': {
        const itext = data.text || '⚡ Переключаюсь на новую задачу';
        UI.showInterruptBadge('interrupted', itext);
        Activity.log('⚡', 'error', itext);
        Messages.finalizeStreaming();
        break;
      }
      // ── Error ──
      case 'error': {
        const msg = data.error || data.message || 'Ошибка';
        Activity.log('❌', 'error', msg);
        Activity.setStatus('error', 'Ошибка');
        Toast.error(msg);
        break;
      }
      // ── Done / End ──
      case 'done':
      case 'end':
      case 'complete': {
        this.onDone(data);
        break;
      }
      // ── Intent ──
      case 'intent': {
        const intent = data.intent || data.text || '';
        if (intent) $('intent-badge').textContent = intent;
        break;
      }
      // ── Model ──
      case 'model': {
        const model = data.model || '';
        if (model) {
          const badge = $('model-badge');
          badge.textContent = model;
          badge.classList.remove('hidden');
        }
        break;
      }
      // ── Screenshot ──
      case 'screenshot': {
        const url = data.url || data.screenshot || '';
        if (url) Activity.addScreenshot(url);
        break;
      }
      // ── Verification ──
      case 'verification':
      case 'qa_result': {
        const passed = data.passed || data.ok;
        Activity.log(passed ? '✅' : '⚠️', passed ? 'ok' : 'error', 'Проверка качества: ' + (passed ? 'пройдена' : 'не пройдена'));
        break;
      }
      default:
        break;
    }
  },

  onDone(data) {
    Messages.finalizeStreaming();
    state.streamingMsgEl = null;
    const content = state.streamingContent;
    if (content) {
      state.messages.push({ role: 'assistant', content, created_at: new Date().toISOString() });
    }
    state.isStreaming = false;
    state.streamingContent = '';
    state.streamingThinking = '';
    this.toolMap = {};
    UI.setStreaming(false);
    Activity.setStatus('done', 'Завершён');
    $('intent-badge').textContent = 'Готов к работе';
    const badge = $('model-badge');
    if (badge) badge.classList.add('hidden');
    Pipeline.hide();
    // Cost
    if (data.cost) Budget.update(data.cost);
    // Notification
    if (Notification.permission === 'granted' && document.hidden) {
      new Notification('ORION', { body: 'Задача выполнена', icon: '/favicon.ico' });
    }
  }
};

/* ── BUDGET ──────────────────────────────────────────────── */
const Budget = {
  update(cost) {
    state.sessionCost = cost;
    const mode = MODE_INFO[state.mode] || MODE_INFO.pro_standard;
    const limit = mode.limit;
    const pct = Math.min(100, (cost / limit) * 100);
    $('budget-text').textContent = `$${cost.toFixed(3)} / $${limit}.00`;
    $('budget-fill').style.width = pct + '%';
    $('input-footer-text').textContent = `ORION Digital · ${mode.label} · $${cost.toFixed(3)} за чат`;
    if (pct > 80) $('budget-fill').style.background = 'var(--error)';
    else if (pct > 60) $('budget-fill').style.background = 'var(--warning)';
    else $('budget-fill').style.background = '';
  }
};

/* ── UI HELPERS ──────────────────────────────────────────── */
const UI = {
  setStreaming(on) {
    $('btn-send').classList.toggle('hidden', on);
    $('btn-stop').classList.toggle('hidden', !on);
    // PATCH 14: Input is ALWAYS active — user can send while agent works
    $('message-input').disabled = false;
    $('btn-attach').disabled = false;
  },
  showInterruptBadge(type, text) {
    // Show a temporary badge above the input when message is queued/appended/interrupted
    let badge = $('interrupt-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'interrupt-badge';
      badge.style.cssText = 'position:absolute;bottom:72px;left:50%;transform:translateX(-50%);'
        + 'background:var(--accent);color:#fff;padding:6px 14px;border-radius:20px;'
        + 'font-size:13px;font-weight:600;z-index:100;opacity:1;transition:opacity 0.5s;'
        + 'pointer-events:none;white-space:nowrap;box-shadow:0 2px 12px rgba(0,0,0,0.2);';
      const inputArea = document.querySelector('.input-area') || document.body;
      inputArea.style.position = 'relative';
      inputArea.appendChild(badge);
    }
    const colors = { queue: '#f59e0b', append: '#10b981', interrupt: '#6366f1', interrupted: '#ef4444' };
    badge.style.background = colors[type] || 'var(--accent)';
    badge.textContent = text;
    badge.style.opacity = '1';
    clearTimeout(badge._timer);
    badge._timer = setTimeout(() => { badge.style.opacity = '0'; }, 3000);
  },
  autoResize(ta) {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  },
  showWelcome(show) {
    const w = $('welcome-screen');
    const m = $('messages-container');
    if (w) w.style.display = show ? '' : 'none';
    if (m) m.style.display = show ? 'none' : '';
  }
};

/* ── CHAT ────────────────────────────────────────────────── */
const Chat = {
  async new() {
    try {
      const data = await API.post('/chats', { title: 'Новый чат' });
      const chat = data.chat || data;
      state.chats.unshift(chat);
      state.currentChatId = chat.id;
      state.messages = [];
      state.totalCost = 0;
      $('chat-title').textContent = 'Новый чат';
      $('messages-container').innerHTML = '';
      UI.showWelcome(true);
      ChatList.render();
      ChatList.setActive(chat.id);
      Activity.clear();
      Budget.update(0);
      $('message-input').focus();
    } catch (e) {
      Toast.error('Не удалось создать чат: ' + e.message);
    }
  },
  async load(chatId) {
    try {
      const data = await API.get('/chats/' + chatId);
      state.currentChatId = chatId;
      state.messages = data.messages || [];
      $('chat-title').textContent = data.chat?.title || data.title || 'Чат';
      $('messages-container').innerHTML = '';
      if (state.messages.length) {
        UI.showWelcome(false);
        state.messages.forEach(msg => {
          const el2 = msg.role === 'user' ? Messages.renderUser(msg) : Messages.renderAgent(msg);
          $('messages-container').appendChild(el2);
        });
        Messages.scrollToBottom();
      } else {
        UI.showWelcome(true);
      }
      ChatList.setActive(chatId);
      Activity.clear();
      Budget.update(data.chat?.total_cost || 0);
    } catch (e) {
      Toast.error('Не удалось загрузить чат: ' + e.message);
    }
  },
  async delete(chatId) {
    try {
      await API.delete('/chats/' + chatId);
      state.chats = state.chats.filter(c => c.id !== chatId);
      if (state.currentChatId === chatId) {
        state.currentChatId = null;
        $('messages-container').innerHTML = '';
        UI.showWelcome(true);
        $('chat-title').textContent = 'Новый чат';
      }
      ChatList.render();
      Toast.success('Чат удалён');
    } catch (e) { Toast.error('Ошибка удаления: ' + e.message); }
  },
  async rename(chatId, title) {
    try {
      await API.put('/chats/' + chatId + '/rename', { title });
      const chat = state.chats.find(c => c.id === chatId);
      if (chat) chat.title = title;
      if (state.currentChatId === chatId) $('chat-title').textContent = title;
      ChatList.render();
    } catch (e) { Toast.error('Ошибка переименования: ' + e.message); }
  },
  async send(text, attachments = []) {
    if (!text.trim()) return;
    // PATCH 14: Allow sending while streaming — backend handles interrupt/queue/append
    if (state.isStreaming && state.currentChatId) {
      // Task is running — send to backend for interrupt/queue/append classification
      const userMsg2 = { role: 'user', content: text, attachments, created_at: new Date().toISOString() };
      state.messages.push(userMsg2);
      document.getElementById('messages-container').appendChild(Messages.renderUser(userMsg2));
      Messages.scrollToBottom();
      try {
        const body2 = { message: text, chat_id: state.currentChatId, mode: state.mode };
        const res2 = await fetch(API_BASE + '/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + state.token },
          body: JSON.stringify(body2),
          signal: AbortSignal.timeout(10000)
        });
        if (res2.ok) {
          const reader2 = res2.body.getReader();
          const decoder2 = new TextDecoder();
          let buf2 = '';
          while (true) {
            const { done, value } = await reader2.read();
            if (done) break;
            buf2 += decoder2.decode(value, { stream: true });
            const lines2 = buf2.split('\n');
            buf2 = lines2.pop();
            for (const ln of lines2) {
              if (!ln.startsWith('data: ')) continue;
              try {
                const d = JSON.parse(ln.slice(6));
                if (d.type === 'queued') UI.showInterruptBadge('queue', d.text || '\u23f0 \u0412 \u043e\u0447\u0435\u0440\u0435\u0434\u0438');
                else if (d.type === 'appended') UI.showInterruptBadge('append', d.text || '\ud83d\udce9 \u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043e');
                else if (d.type === 'interrupted') UI.showInterruptBadge('interrupted', d.text || '\u26a1 \u041f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0430\u044e\u0441\u044c');
              } catch (_) {}
            }
          }
        }
      } catch (e2) { Toast.error('\u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438: ' + e2.message); }
      return;
    }
    if (!state.currentChatId) await this.new();
    if (!state.currentChatId) return;

    // Add user message to UI
    const userMsg = { role: 'user', content: text, attachments, created_at: new Date().toISOString() };
    state.messages.push(userMsg);
    $('messages-container').appendChild(Messages.renderUser(userMsg));
    UI.showWelcome(false);
    Messages.scrollToBottom();

    // Add streaming placeholder
    const streamEl = Messages.renderStreaming();
    $('messages-container').appendChild(streamEl);
    Messages.scrollToBottom();

    state.isStreaming = true;
    state.streamingContent = '';
    state.streamingThinking = '';
    state.abortController = new AbortController();
    UI.setStreaming(true);
    Activity.clear();
    Activity.setStatus('running', 'Думает...');
    Activity.open();
    SSE.toolMap = {};

    try {
      const body = {
        message: text,
        chat_id: state.currentChatId,
        mode: state.mode,
        verification: state.qaEnabled,
      };
      if (attachments.length) body.attachments = attachments;

      const res = await fetch(API_BASE + '/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + state.token,
        },
        body: JSON.stringify(body),
        signal: state.abortController.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || res.statusText);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          if (line.startsWith('data: ')) {
            const raw = line.slice(6).trim();
            if (raw === '[DONE]') { SSE.onDone({}); break; }
            try {
              const ev = JSON.parse(raw);
              const type = ev.type || ev.event || 'content';
              SSE.handle(type, ev);
            } catch { /* skip */ }
          } else if (line.startsWith('event: ')) {
            // SSE event type line — handled on next data line
          }
        }
      }
    } catch (e) {
      if (e.name === 'AbortError') {
        Activity.log('⏹', 'error', 'Остановлено пользователем');
        Messages.finalizeStreaming();
        state.streamingContent = state.streamingContent || '[Остановлено]';
      } else {
        Toast.error('Ошибка: ' + e.message);
        Activity.setStatus('error', 'Ошибка');
        const errEl = $('streaming-msg');
        if (errEl) {
          const md = errEl.querySelector('.msg-md');
          if (md) md.innerHTML = '<span style="color:var(--error)">Ошибка: ' + esc(e.message) + '</span>';
        }
      }
    } finally {
      state.isStreaming = false;
      state.abortController = null;
      UI.setStreaming(false);
      state.attachments = [];
      $('attachments-preview').innerHTML = '';
    }
  },
  stop() {
    if (state.abortController) state.abortController.abort();
  },
  regenerate() {
    const lastUser = [...state.messages].reverse().find(m => m.role === 'user');
    if (!lastUser) return;
    // Remove last AI message from DOM
    const msgs = $('messages-container').querySelectorAll('.msg-agent');
    if (msgs.length) msgs[msgs.length-1].remove();
    // Remove from state
    const idx = [...state.messages].reverse().findIndex(m => m.role === 'assistant');
    if (idx !== -1) state.messages.splice(state.messages.length - 1 - idx, 1);
    this.send(lastUser.content, lastUser.attachments || []);
  },
  async sendTakeover(text) {
    if (!text.trim() || !state.currentChatId) return;
    try {
      await API.post('/chats/' + state.currentChatId + '/human_response', { response: text });
      Activity.hideTakeover();
      Toast.success('Ответ отправлен');
    } catch (e) { Toast.error('Ошибка: ' + e.message); }
  }
};

/* ── CONTEXT MENU ────────────────────────────────────────── */
const CtxMenu = {
  show(e, chatId) {
    state.ctxChatId = chatId;
    const menu = $('ctx-menu');
    menu.classList.remove('hidden');
    const x = Math.min(e.clientX, window.innerWidth - 180);
    const y = Math.min(e.clientY, window.innerHeight - 120);
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
  },
  hide() {
    $('ctx-menu').classList.add('hidden');
    state.ctxChatId = null;
  }
};

/* ── VOICE INPUT ─────────────────────────────────────────── */
const VoiceInput = {
  rec: null,
  active: false,
  toggle() {
    if (this.active) { this.stop(); return; }
    if (!('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
      Toast.warning('Голосовой ввод не поддерживается в этом браузере');
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.rec = new SR();
    this.rec.lang = 'ru-RU'; this.rec.continuous = false; this.rec.interimResults = false;
    this.rec.onresult = (e) => {
      const text = e.results[0][0].transcript;
      $('message-input').value += text;
      UI.autoResize($('message-input'));
    };
    this.rec.onerror = () => { this.stop(); Toast.error('Ошибка голосового ввода'); };
    this.rec.onend = () => this.stop();
    this.rec.start();
    this.active = true;
    $('btn-voice').classList.add('recording');
    Toast.info('Говорите...');
  },
  stop() {
    if (this.rec) { try { this.rec.stop(); } catch {} this.rec = null; }
    this.active = false;
    $('btn-voice').classList.remove('recording');
  }
};

/* ── ADMIN ───────────────────────────────────────────────── */
const Admin = {
  async load() {
    try {
      const [users, stats] = await Promise.all([
        API.get('/admin/users').catch(() => ({ users: [] })),
        API.get('/admin/stats').catch(() => ({})),
      ]);
      this.renderStats(stats);
      this.renderUsers(users.users || []);
    } catch (e) { Toast.error('Ошибка загрузки: ' + e.message); }
  },
  renderStats(s) {
    const grid = $('admin-stats');
    if (!grid) return;
    const items = [
      { val: s.total_users || 0, label: 'Пользователей' },
      { val: s.total_chats || 0, label: 'Чатов' },
      { val: '$' + (s.total_cost || 0).toFixed(2), label: 'Потрачено' },
    ];
    grid.innerHTML = items.map(i => `<div class="stat-card"><div class="stat-val">${i.val}</div><div class="stat-label">${i.label}</div></div>`).join('');
  },
  renderUsers(users) {
    const wrap = $('users-table-wrap');
    if (!wrap) return;
    // Create user form
    const createForm = `
      <div class="create-user-form" style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px">
        <h4 style="margin:0 0 12px;font-size:14px;color:var(--text-primary)">➕ Создать пользователя</h4>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:8px">
          <input id="new-user-email" type="email" placeholder="Email" class="input-field" style="padding:8px 12px;font-size:13px" />
          <input id="new-user-password" type="password" placeholder="Пароль" class="input-field" style="padding:8px 12px;font-size:13px" />
          <select id="new-user-role" class="input-field" style="padding:8px 12px;font-size:13px">
            <option value="user">Пользователь</option>
            <option value="admin">Администратор</option>
            <option value="viewer">Просмотр</option>
          </select>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <input id="new-user-name" type="text" placeholder="Имя (необязательно)" class="input-field" style="padding:8px 12px;font-size:13px;flex:1" />
          <input id="new-user-limit" type="number" placeholder="Лимит $" value="100" class="input-field" style="padding:8px 12px;font-size:13px;width:100px" />
          <button id="btn-create-user" class="btn primary" style="padding:8px 16px;font-size:13px;white-space:nowrap">Создать</button>
        </div>
        <div id="create-user-error" style="color:#ef4444;font-size:12px;margin-top:6px;display:none"></div>
      </div>
    `;
    wrap.innerHTML = createForm;
    // Bind create button
    const createBtn = wrap.querySelector('#btn-create-user');
    createBtn.addEventListener('click', () => Admin.createUser());
    // Users table
    if (!users.length) {
      wrap.insertAdjacentHTML('beforeend', '<p style="color:var(--text-muted);padding:16px">Нет пользователей</p>');
      return;
    }
    const table = el('table', 'users-table');
    table.innerHTML = `<thead><tr><th>Email</th><th>Имя</th><th>Роль</th><th>Чатов</th><th>Стоимость</th><th>Статус</th><th></th></tr></thead>`;
    const tbody = el('tbody');
    users.forEach(u => {
      const tr = el('tr');
      const uid = esc(String(u.id || u.user_id || ''));
      tr.innerHTML = `
        <td>${esc(u.email || u.username || u.login || '')}</td>
        <td>${esc(u.name || u.full_name || '')}</td>
        <td><span class="user-status-badge active" style="background:${u.role==='admin'?'#7c3aed22':'#16a34a22'};color:${u.role==='admin'?'#a78bfa':'#4ade80'}">${esc(u.role || 'user')}</span></td>
        <td>${u.total_chats || u.chats_count || 0}</td>
        <td>$${(u.total_spent || u.total_cost || 0).toFixed(3)}</td>
        <td><span class="user-status-badge ${u.blocked || !u.is_active ? 'blocked' : 'active'}">${u.blocked || !u.is_active ? 'Заблокирован' : 'Активен'}</span></td>
        <td style="display:flex;gap:4px;flex-wrap:wrap">
          <button class="btn-sm ${u.blocked || !u.is_active ? 'primary' : 'danger'}" onclick="Admin.toggleBlock('${uid}', ${!(u.blocked || !u.is_active)})">${u.blocked || !u.is_active ? 'Разблокировать' : 'Заблокировать'}</button>
          <button class="btn-sm" onclick="Admin.editUser('${uid}', '${esc(u.email||'')}', '${esc(u.name||'')}', '${esc(u.role||'user')}', ${u.monthly_limit||100})">Редактировать</button>
          <button class="btn-sm danger" onclick="Admin.deleteUser('${uid}', '${esc(u.email||'')}')">Удалить</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
  },
  async createUser() {
    const email = $('new-user-email').value.trim();
    const password = $('new-user-password').value;
    const role = $('new-user-role').value;
    const name = $('new-user-name').value.trim();
    const monthly_limit = parseFloat($('new-user-limit').value) || 100;
    const errEl = $('create-user-error');
    errEl.style.display = 'none';
    if (!email || !password) {
      errEl.textContent = 'Email и пароль обязательны';
      errEl.style.display = 'block';
      return;
    }
    if (password.length < 6) {
      errEl.textContent = 'Пароль должен быть не менее 6 символов';
      errEl.style.display = 'block';
      return;
    }
    const btn = $('btn-create-user');
    btn.disabled = true;
    btn.textContent = 'Создаю...';
    try {
      await API.post('/admin/users', { email, password, name: name || email.split('@')[0], role, monthly_limit });
      Toast.success('Пользователь создан: ' + email);
      $('new-user-email').value = '';
      $('new-user-password').value = '';
      $('new-user-name').value = '';
      $('new-user-limit').value = '100';
      this.load();
    } catch (e) {
      errEl.textContent = e.message || 'Ошибка создания пользователя';
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Создать';
    }
  },
  async toggleBlock(userId, block) {
    try {
      const res = await API.post('/admin/users/' + userId + '/toggle', {});
      Toast.success(res.is_active ? 'Пользователь разблокирован' : 'Пользователь заблокирован');
      this.load();
    } catch (e) { Toast.error('Ошибка: ' + e.message); }
  },
  async editUser(userId, email, name, role, limit) {
    const newName = prompt(`Имя пользователя (${email}):`, name);
    if (newName === null) return; // cancelled
    const newRole = prompt('Роль (user/admin/viewer):', role);
    if (newRole === null) return;
    if (!['user', 'admin', 'viewer'].includes(newRole)) {
      Toast.error('Неверная роль. Допустимо: user, admin, viewer');
      return;
    }
    const newLimit = parseFloat(prompt('Лимит $ в месяц:', limit));
    if (isNaN(newLimit)) { Toast.error('Неверный лимит'); return; }
    try {
      await API.put('/admin/users/' + userId, { name: newName, role: newRole, monthly_limit: newLimit });
      Toast.success('Пользователь обновлён: ' + email);
      this.load();
    } catch (e) { Toast.error('Ошибка: ' + e.message); }
  },
  async deleteUser(userId, email) {
    if (!confirm(`Удалить пользователя ${email}? Это действие необратимо!`)) return;
    try {
      await API.delete('/admin/users/' + userId);
      Toast.success('Пользователь удалён: ' + email);
      this.load();
    } catch (e) { Toast.error('Ошибка удаления: ' + e.message); }
  },
  async loadApiKeys() {
    const status = document.getElementById('api-keys-status');
    if (status) status.textContent = 'Загружаю...';
    try {
      const res = await API.get('/admin/apikeys');
      const keys = res.keys || {};
      const fieldMap = {
        'openrouter': 'key-openrouter',
        'minimax': 'key-minimax',
        'rucaptcha': 'key-rucaptcha',
        'anthropic': 'key-anthropic',
        'openai': 'key-openai',
      };
      for (const [k, id] of Object.entries(fieldMap)) {
        const el = document.getElementById(id);
        if (el && keys[k]) el.placeholder = keys[k]; // show masked value as placeholder
      }
      if (status) { status.textContent = '✓ Загружено'; status.style.color = '#4ade80'; }
    } catch (e) {
      if (status) { status.textContent = 'Ошибка: ' + e.message; status.style.color = '#ef4444'; }
    }
  },
  async saveApiKeys() {
    const status = document.getElementById('api-keys-status');
    if (status) status.textContent = 'Сохраняю...';
    const fieldMap = {
      'openrouter': 'key-openrouter',
      'minimax': 'key-minimax',
      'rucaptcha': 'key-rucaptcha',
      'anthropic': 'key-anthropic',
      'openai': 'key-openai',
    };
    const payload = {};
    for (const [k, id] of Object.entries(fieldMap)) {
      const el = document.getElementById(id);
      if (el && el.value.trim()) payload[k] = el.value.trim();
    }
    if (!Object.keys(payload).length) {
      if (status) { status.textContent = 'Нет изменений'; status.style.color = '#f59e0b'; }
      return;
    }
    try {
      const res = await API.put('/admin/apikeys', payload);
      const updated = res.updated || [];
      if (status) { status.textContent = '✓ Сохранено: ' + updated.join(', '); status.style.color = '#4ade80'; }
      // Clear fields after save
      for (const id of Object.values(fieldMap)) {
        const el = document.getElementById(id);
        if (el) el.value = '';
      }
      Toast.success('API ключи обновлены: ' + updated.join(', '));
    } catch (e) {
      if (status) { status.textContent = 'Ошибка: ' + e.message; status.style.color = '#ef4444'; }
      Toast.error('Ошибка сохранения: ' + e.message);
    }
  }
};

/* ── FILE UPLOAD ─────────────────────────────────────────── */
const FileUpload = {
  async upload(files) {
    const preview = $('attachments-preview');
    for (const file of files) {
      const chip = el('div', 'attachment-chip');
      // Show loading spinner while uploading
      chip.innerHTML = `<span class="upload-spinner">⏳</span> ${esc(file.name)}`;
      chip.style.opacity = '0.6';
      preview.appendChild(chip);
      // Upload to server
      try {
        const fd = new FormData();
        fd.append('file', file);
        const res = await fetch(API_BASE + '/upload', {
          method: 'POST',
          headers: { 'Authorization': 'Bearer ' + state.token },
          body: fd,
        });
        if (res.ok) {
          const data = await res.json();
          state.attachments.push({ name: file.name, url: data.url || data.path, type: file.type });
          // Show success state
          chip.innerHTML = `✅ ${esc(file.name)} <span class="remove" data-name="${esc(file.name)}">×</span>`;
          chip.style.opacity = '1';
        } else {
          chip.innerHTML = `❌ ${esc(file.name)} <span class="remove" data-name="${esc(file.name)}">×</span>`;
          chip.style.opacity = '1';
          Toast.error('Ошибка загрузки: ' + file.name);
        }
      } catch (err) {
        state.attachments.push({ name: file.name, type: file.type });
        chip.innerHTML = `📎 ${esc(file.name)} <span class="remove" data-name="${esc(file.name)}">×</span>`;
        chip.style.opacity = '1';
      }
    }
    preview.querySelectorAll('.remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const name = btn.dataset.name;
        btn.closest('.attachment-chip').remove();
        state.attachments = state.attachments.filter(a => a.name !== name);
      });
    });
  }
};

/* ── APP INIT ────────────────────────────────────────────── */
const App = {
  async init() {
    // Load chats
    await ChatList.load();
    // Mode
    const modeSelect = $('mode-select');
    modeSelect.value = state.mode;
    this.updateModeDesc(state.mode);
    // If no chat, show welcome
    if (!state.currentChatId) UI.showWelcome(true);
    // Bind events
    this.bindEvents();
    // Templates
    this.renderTemplates();
  },
  updateModeDesc(mode) {
    const info = MODE_INFO[mode] || MODE_INFO.pro_standard;
    $('mode-description').textContent = info.desc;
    Budget.update(state.sessionCost);
  },
  renderTemplates() {
    const grid = $('templates-grid');
    if (!grid) return;
    grid.innerHTML = TEMPLATES.map(t => `
      <div class="template-card" data-prompt="${esc(t.prompt)}">
        <div class="template-icon">${t.icon}</div>
        <div class="template-name">${esc(t.name)}</div>
        <div class="template-desc">${esc(t.desc)}</div>
      </div>
    `).join('');
    grid.querySelectorAll('.template-card').forEach(card => {
      card.addEventListener('click', () => {
        $('message-input').value = card.dataset.prompt;
        UI.autoResize($('message-input'));
        $('templates-modal').classList.add('hidden');
        $('message-input').focus();
      });
    });
  },
  bindEvents() {
    // Auth form
    $('auth-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      await Auth.login($('auth-login').value, $('auth-password').value);
    });
    $('toggle-pw').addEventListener('click', () => {
      const pw = $('auth-password');
      pw.type = pw.type === 'password' ? 'text' : 'password';
    });

    // New chat
    $('btn-new-chat').addEventListener('click', () => Chat.new());

    // Send message
    $('btn-send').addEventListener('click', () => {
      const text = $('message-input').value.trim();
      if (!text) return;
      $('message-input').value = '';
      UI.autoResize($('message-input'));
      Chat.send(text, [...state.attachments]);
    });
    $('btn-stop').addEventListener('click', () => Chat.stop());

    // Textarea
    const ta = $('message-input');
    ta.addEventListener('input', () => UI.autoResize(ta));
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const text = ta.value.trim();
        if (!text) return; // PATCH 14: allow sending while streaming
        ta.value = ''; UI.autoResize(ta);
        Chat.send(text, [...state.attachments]);
      }
    });

    // Welcome chips
    document.querySelectorAll('.welcome-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const prompt = chip.dataset.prompt;
        $('message-input').value = prompt;
        UI.autoResize($('message-input'));
        $('message-input').focus();
      });
    });

    // Sidebar toggle
    $('btn-sidebar-toggle').addEventListener('click', () => {
      const sb = $('sidebar');
      sb.classList.toggle('collapsed');
      state.sidebarCollapsed = sb.classList.contains('collapsed');
    });

    // Activity toggle
    $('btn-activity-toggle').addEventListener('click', () => Activity.toggle());
    $('btn-collapse-act').addEventListener('click', () => Activity.close());

    // Theme
    $('btn-theme').addEventListener('click', () => Theme.toggle());

    // Settings
    $('btn-settings').addEventListener('click', () => $('settings-modal').classList.remove('hidden'));
    $('btn-settings-close').addEventListener('click', () => $('settings-modal').classList.add('hidden'));

    // Templates
    $('btn-templates').addEventListener('click', () => $('templates-modal').classList.remove('hidden'));
    $('btn-templates-close').addEventListener('click', () => $('templates-modal').classList.add('hidden'));

    // Admin
    $('btn-admin').addEventListener('click', () => {
      $('admin-modal').classList.remove('hidden');
      Admin.load();
    });
    $('btn-admin-close').addEventListener('click', () => $('admin-modal').classList.add('hidden'));

    // Logout
    $('btn-logout').addEventListener('click', () => Auth.logout());

    // Mode select
    $('mode-select').addEventListener('change', (e) => {
      state.mode = e.target.value;
      localStorage.setItem('orion_mode', state.mode);
      this.updateModeDesc(state.mode);
    });

    // QA toggle
    $('qa-toggle').addEventListener('click', () => {
      state.qaEnabled = !state.qaEnabled;
      $('qa-toggle').classList.toggle('active', state.qaEnabled);
      $('verification-toggle').checked = state.qaEnabled;
    });
    $('verification-toggle').addEventListener('change', (e) => {
      state.qaEnabled = e.target.checked;
      $('qa-toggle').classList.toggle('active', state.qaEnabled);
    });

    // File attach
    $('btn-attach').addEventListener('click', () => $('file-input').click());
    $('file-input').addEventListener('change', (e) => {
      if (e.target.files.length) FileUpload.upload(Array.from(e.target.files));
    });

    // Drag & drop
    const chatArea = $('chat-area');
    chatArea.addEventListener('dragover', (e) => { e.preventDefault(); $('drop-zone-overlay').classList.remove('hidden'); });
    chatArea.addEventListener('dragleave', () => $('drop-zone-overlay').classList.add('hidden'));
    chatArea.addEventListener('drop', (e) => {
      e.preventDefault();
      $('drop-zone-overlay').classList.add('hidden');
      if (e.dataTransfer.files.length) FileUpload.upload(Array.from(e.dataTransfer.files));
    });

    // Chat search
    $('chat-search').addEventListener('input', (e) => ChatList.render(e.target.value));

    // Edit title
    $('btn-edit-title').addEventListener('click', () => {
      const title = $('chat-title');
      title.contentEditable = 'true';
      title.focus();
      const range = document.createRange();
      range.selectNodeContents(title);
      window.getSelection().removeAllRanges();
      window.getSelection().addRange(range);
    });
    $('chat-title').addEventListener('blur', () => {
      const title = $('chat-title');
      title.contentEditable = 'false';
      if (state.currentChatId) Chat.rename(state.currentChatId, title.textContent.trim());
    });
    $('chat-title').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); $('chat-title').blur(); }
      if (e.key === 'Escape') { $('chat-title').blur(); }
    });

    // Context menu
    $('ctx-rename').addEventListener('click', () => {
      if (!state.ctxChatId) return;
      const name = prompt('Новое название:');
      if (name) Chat.rename(state.ctxChatId, name);
      CtxMenu.hide();
    });
    $('ctx-delete').addEventListener('click', () => {
      if (!state.ctxChatId) return;
      if (confirm('Удалить чат?')) Chat.delete(state.ctxChatId);
      CtxMenu.hide();
    });
    $('ctx-export').addEventListener('click', () => {
      if (!state.currentChatId) return;
      const text = state.messages.map(m => `[${m.role}]\n${m.content}`).join('\n\n---\n\n');
      const blob = new Blob([text], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'orion-chat-' + state.currentChatId + '.txt';
      a.click();
      CtxMenu.hide();
    });
    document.addEventListener('click', (e) => {
      if (!$('ctx-menu').contains(e.target)) CtxMenu.hide();
    });

    // Takeover
    $('btn-takeover-send').addEventListener('click', () => {
      const text = $('takeover-input').value.trim();
      if (text) { Chat.sendTakeover(text); $('takeover-input').value = ''; }
    });
    $('takeover-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { const text = e.target.value.trim(); if (text) { Chat.sendTakeover(text); e.target.value = ''; } }
    });

    // Modal tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        btn.closest('.modal').querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
        btn.closest('.modal').querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + tab));
        if (tab === 'memory') Admin.loadMemory?.();
        if (tab === 'apikeys') Admin.loadApiKeys?.();
      });
    });

    // API Keys panel
    const btnSaveKeys = document.getElementById('btn-save-api-keys');
    const btnLoadKeys = document.getElementById('btn-load-api-keys');
    if (btnSaveKeys) btnSaveKeys.addEventListener('click', () => Admin.saveApiKeys());
    if (btnLoadKeys) btnLoadKeys.addEventListener('click', () => Admin.loadApiKeys());

    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
      overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.classList.add('hidden'); });
    });

    // Notifications button
    const notifBtn = $('btn-notif-perm');
    if (notifBtn) notifBtn.addEventListener('click', () => Notification.requestPermission().then(p => Toast.info('Статус уведомлений: ' + p)));

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key === 'k') { e.preventDefault(); Chat.new(); }
      if (meta && e.key === 'b') { e.preventDefault(); $('btn-sidebar-toggle').click(); }
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => m.classList.add('hidden'));
        CtxMenu.hide();
      }
    });

    // Resize handles
    this.initResize();
  },
  initResize() {
    let resizing = null;
    let startX = 0;
    let startW = 0;

    const onDown = (e, which) => {
      resizing = which;
      startX = e.clientX;
      const el2 = which === 'sidebar' ? $('sidebar') : $('activity-panel');
      startW = el2.offsetWidth;
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    };

    $('resize-sidebar').addEventListener('mousedown', (e) => onDown(e, 'sidebar'));
    $('resize-activity').addEventListener('mousedown', (e) => onDown(e, 'activity'));

    document.addEventListener('mousemove', (e) => {
      if (!resizing) return;
      const diff = e.clientX - startX;
      if (resizing === 'sidebar') {
        const w = Math.max(180, Math.min(400, startW + diff));
        $('sidebar').style.width = w + 'px';
        $('sidebar').style.minWidth = w + 'px';
      } else {
        const w = Math.max(240, Math.min(500, startW - diff));
        $('activity-panel').style.width = w + 'px';
        $('activity-panel').style.minWidth = w + 'px';
      }
    });

    document.addEventListener('mouseup', () => {
      resizing = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    });
  }
};

/* ── BOOT ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  Theme.init();
  Auth.init();
});
