// ARCANE AgentBrowser — "Warm Intelligence" design
// Live browser view showing agent controlling the browser in real time
// Features: animated agent cursor, click ripples, scroll simulation, URL bar, page tabs, action overlay

import { useState, useEffect, useRef, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  ArrowLeft, ArrowRight, RefreshCw, Lock, Globe, X, Plus,
  MousePointer2, Eye, Loader2, Monitor, ExternalLink, Maximize2,
  ZoomIn, ZoomOut, RotateCcw, WifiOff, AlertTriangle, ShieldOff
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

// ─── Mock page data ───────────────────────────────────────────────────────────

interface BrowserPage {
  id: string;
  title: string;
  url: string;
  favicon?: string;
  status: "loading" | "loaded" | "error";
  html: string;
  agentActions?: AgentAction[];
}

interface AgentAction {
  type: "click" | "scroll" | "type" | "hover" | "select";
  x?: number;
  y?: number;
  text?: string;
  label: string;
  delay: number; // ms after page load
}

const PAGES: BrowserPage[] = [
  {
    id: "p1",
    title: "Bitrix Admin Panel",
    url: "https://185.22.xx.xx/bitrix/admin/",
    status: "loaded",
    agentActions: [
      { type: "click",  x: 50,  y: 35,  label: "Нажимает «Установка»",  delay: 800 },
      { type: "scroll", x: 50,  y: 60,  label: "Прокручивает страницу",  delay: 2000 },
      { type: "click",  x: 70,  y: 70,  label: "Выбирает базу данных",   delay: 3200 },
      { type: "type",   x: 70,  y: 70,  text: "bitrix_db", label: "Вводит имя БД", delay: 4000 },
      { type: "click",  x: 50,  y: 85,  label: "Нажимает «Далее»",       delay: 5200 },
    ],
    html: `
      <div style="font-family:system-ui,sans-serif;font-size:13px;background:#f5f5f5;min-height:100%;padding:0">
        <div style="background:#1a56db;color:white;padding:10px 16px;display:flex;align-items:center;gap:10px">
          <div style="font-weight:700;font-size:15px">1С-Битрикс</div>
          <div style="opacity:0.7;font-size:11px">Панель управления</div>
          <div style="margin-left:auto;display:flex;gap:8px;font-size:11px">
            <span style="opacity:0.8">admin</span>
            <span style="opacity:0.5">|</span>
            <span style="opacity:0.8;cursor:pointer">Выход</span>
          </div>
        </div>
        <div style="display:flex;height:calc(100% - 36px)">
          <div style="width:180px;background:#fff;border-right:1px solid #e5e7eb;padding:8px 0;font-size:12px">
            <div style="padding:6px 14px;color:#1a56db;font-weight:600;background:#eff6ff;border-left:3px solid #1a56db">Установка</div>
            <div style="padding:6px 14px;color:#374151;cursor:pointer">Модули</div>
            <div style="padding:6px 14px;color:#374151;cursor:pointer">Настройки</div>
            <div style="padding:6px 14px;color:#374151;cursor:pointer">Пользователи</div>
            <div style="padding:6px 14px;color:#374151;cursor:pointer">Структура сайта</div>
            <div style="padding:6px 14px;color:#374151;cursor:pointer">Контент</div>
            <div style="padding:6px 14px;color:#374151;cursor:pointer">Маркетинг</div>
          </div>
          <div style="flex:1;padding:16px">
            <div style="font-size:16px;font-weight:600;color:#111827;margin-bottom:12px">Мастер установки Битрикс</div>
            <div style="background:white;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:12px">
              <div style="font-size:12px;font-weight:600;color:#374151;margin-bottom:8px">Шаг 2: Настройка базы данных</div>
              <div style="display:grid;gap:8px">
                <div>
                  <label style="font-size:11px;color:#6b7280;display:block;margin-bottom:3px">Хост MySQL</label>
                  <input style="width:100%;border:1px solid #d1d5db;border-radius:4px;padding:5px 8px;font-size:12px;box-sizing:border-box" value="localhost" readonly />
                </div>
                <div>
                  <label style="font-size:11px;color:#6b7280;display:block;margin-bottom:3px">Имя базы данных</label>
                  <input style="width:100%;border:2px solid #1a56db;border-radius:4px;padding:5px 8px;font-size:12px;box-sizing:border-box;background:#eff6ff" value="bitrix_db" readonly />
                </div>
                <div>
                  <label style="font-size:11px;color:#6b7280;display:block;margin-bottom:3px">Пользователь</label>
                  <input style="width:100%;border:1px solid #d1d5db;border-radius:4px;padding:5px 8px;font-size:12px;box-sizing:border-box" value="bitrix_user" readonly />
                </div>
              </div>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
              <button style="padding:7px 16px;border:1px solid #d1d5db;border-radius:6px;font-size:12px;background:white;cursor:pointer">Назад</button>
              <button style="padding:7px 16px;background:#1a56db;color:white;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600">Далее →</button>
            </div>
          </div>
        </div>
      </div>
    `,
  },
  {
    id: "p2",
    title: "SSL Certificate Setup",
    url: "https://185.22.xx.xx/ssl-setup",
    status: "loaded",
    agentActions: [
      { type: "click",  x: 30, y: 40, label: "Открывает терминал",       delay: 600 },
      { type: "type",   x: 50, y: 60, text: "certbot --nginx", label: "Вводит команду certbot", delay: 1500 },
      { type: "scroll", x: 50, y: 70, label: "Читает вывод команды",      delay: 3000 },
      { type: "click",  x: 60, y: 80, label: "Подтверждает домен",        delay: 4200 },
    ],
    html: `
      <div style="font-family:monospace;font-size:12px;background:#0d1117;color:#c9d1d9;min-height:100%;padding:16px">
        <div style="color:#58a6ff;margin-bottom:8px">root@server:~# certbot --nginx -d example.com</div>
        <div style="color:#3fb950;margin-bottom:4px">Saving debug log to /var/log/letsencrypt/letsencrypt.log</div>
        <div style="color:#c9d1d9;margin-bottom:4px">Requesting a certificate for example.com</div>
        <div style="color:#3fb950;margin-bottom:4px">Successfully received certificate.</div>
        <div style="color:#c9d1d9;margin-bottom:8px">Certificate is saved at: /etc/letsencrypt/live/example.com/fullchain.pem</div>
        <div style="color:#c9d1d9;margin-bottom:4px">Deploying certificate to VirtualHost /etc/nginx/sites-enabled/default</div>
        <div style="color:#3fb950;margin-bottom:8px">Successfully deployed certificate for example.com</div>
        <div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px;margin-top:8px">
          <div style="color:#58a6ff;font-weight:bold;margin-bottom:6px">✓ Congratulations!</div>
          <div style="color:#c9d1d9;font-size:11px">Your certificate and chain have been saved at:</div>
          <div style="color:#3fb950;font-size:11px">/etc/letsencrypt/live/example.com/fullchain.pem</div>
          <div style="color:#c9d1d9;font-size:11px;margin-top:4px">Expiry date: 2024-06-20</div>
        </div>
        <div style="color:#58a6ff;margin-top:12px">root@server:~# nginx -t</div>
        <div style="color:#3fb950">nginx: the configuration file /etc/nginx/nginx.conf syntax is ok</div>
        <div style="color:#3fb950">nginx: configuration file /etc/nginx/nginx.conf test is successful</div>
        <div style="color:#58a6ff;margin-top:8px">root@server:~# systemctl reload nginx</div>
        <div style="color:#3fb950">● nginx.service reloaded</div>
        <div style="color:#58a6ff;margin-top:8px">root@server:~# <span style="animation:blink 1s infinite">█</span></div>
      </div>
    `,
  },
  {
    id: "p3",
    title: "Google Search",
    url: "https://www.google.com/search?q=nginx+ssl+configuration",
    status: "loaded",
    agentActions: [
      { type: "click",  x: 50, y: 20, label: "Кликает на строку поиска",  delay: 500 },
      { type: "scroll", x: 50, y: 50, label: "Читает результаты",          delay: 1800 },
      { type: "click",  x: 50, y: 45, label: "Открывает первый результат", delay: 3000 },
    ],
    html: `
      <div style="font-family:arial,sans-serif;font-size:14px;background:white;min-height:100%;padding:0">
        <div style="background:white;border-bottom:1px solid #e8eaed;padding:8px 16px;display:flex;align-items:center;gap:12px">
          <div style="font-size:20px;font-weight:700;color:#4285f4">G<span style="color:#ea4335">o</span><span style="color:#fbbc05">o</span><span style="color:#4285f4">g</span><span style="color:#34a853">l</span><span style="color:#ea4335">e</span></div>
          <div style="flex:1;border:1px solid #dfe1e5;border-radius:24px;padding:6px 16px;font-size:13px;color:#202124;display:flex;align-items:center;gap:8px;max-width:500px">
            <span>nginx ssl configuration</span>
          </div>
        </div>
        <div style="padding:12px 16px">
          <div style="font-size:11px;color:#70757a;margin-bottom:12px">Около 12 400 000 результатов (0.42 сек.)</div>
          ${["nginx.org — SSL Termination Configuration Guide",
             "DigitalOcean — How To Secure Nginx with Let's Encrypt",
             "Mozilla SSL Config Generator — Recommended Configurations"].map((title, i) => `
            <div style="margin-bottom:16px;padding:12px;border-radius:8px;${i === 0 ? 'background:#f0f7ff;border:1px solid #c2d8f7' : ''}">
              <div style="font-size:11px;color:#202124;margin-bottom:2px">${["nginx.org", "digitalocean.com", "ssl-config.mozilla.org"][i]} › docs</div>
              <div style="font-size:15px;color:#1a0dab;cursor:pointer;margin-bottom:4px">${title}</div>
              <div style="font-size:13px;color:#4d5156;line-height:1.5">Полное руководство по настройке SSL/TLS в nginx. Включает примеры конфигурации для различных уровней безопасности...</div>
            </div>
          `).join("")}
        </div>
      </div>
    `,
  },
  {
    id: "p4",
    title: "Server Dashboard",
    url: "https://185.22.xx.xx:8080/dashboard",
    status: "loading",
    agentActions: [],
    html: "",
  },
];

// ─── Agent Cursor ─────────────────────────────────────────────────────────────

interface CursorPos { x: number; y: number; }

function AgentCursor({ pos, action }: { pos: CursorPos; action?: string }) {
  return (
    <motion.div
      className="absolute pointer-events-none z-50"
      animate={{ left: `${pos.x}%`, top: `${pos.y}%` }}
      transition={{ type: "spring", stiffness: 120, damping: 20 }}
      style={{ transform: "translate(-4px, -4px)" }}
    >
      <div className="relative">
        <MousePointer2 size={18} className="text-indigo-600 drop-shadow-md" fill="#6366f1" />
        {action && (
          <motion.div
            initial={{ opacity: 0, y: 4, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.9 }}
            className="absolute left-5 top-0 bg-indigo-600 text-white text-[10px] font-medium px-2 py-1 rounded-md whitespace-nowrap shadow-lg"
          >
            {action}
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

// ─── Click Ripple ─────────────────────────────────────────────────────────────

function ClickRipple({ x, y, id }: { x: number; y: number; id: number }) {
  return (
    <motion.div
      key={id}
      className="absolute pointer-events-none z-40 rounded-full border-2 border-indigo-400"
      style={{ left: `${x}%`, top: `${y}%`, transform: "translate(-50%, -50%)" }}
      initial={{ width: 0, height: 0, opacity: 0.8 }}
      animate={{ width: 40, height: 40, opacity: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
    />
  );
}

// ─── Main AgentBrowser ────────────────────────────────────────────────────────

export type BrowserOfflineReason = "sandbox_unavailable" | "permission_denied" | "reconnecting" | "none";

interface AgentBrowserProps {
  isRunning?: boolean;
  currentUrl?: string;
  currentAction?: string;
  offlineReason?: BrowserOfflineReason;
  onRetry?: () => void;
}

export function AgentBrowser({ isRunning = false, currentUrl, currentAction, offlineReason = "none", onRetry }: AgentBrowserProps) {
  // Offline / permission-denied overlay
  if (offlineReason !== "none") {
    return <BrowserOfflineOverlay reason={offlineReason} onRetry={onRetry} />;
  }
  const [pageIndex, setPageIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [urlInput, setUrlInput] = useState(PAGES[0].url);
  const [cursorPos, setCursorPos] = useState<CursorPos>({ x: 50, y: 50 });
  const [cursorAction, setCursorAction] = useState<string | undefined>();
  const [ripples, setRipples] = useState<{ x: number; y: number; id: number }[]>([]);
  const [agentActive, setAgentActive] = useState(false);
  const [zoom, setZoom] = useState(100);
  const actionTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const rippleId = useRef(0);

  const page = PAGES[pageIndex];

  // Clear timers on unmount
  useEffect(() => {
    return () => actionTimers.current.forEach(clearTimeout);
  }, []);

  // Run agent actions when page loads and isRunning
  const runAgentActions = useCallback((actions: AgentAction[]) => {
    actionTimers.current.forEach(clearTimeout);
    actionTimers.current = [];
    setAgentActive(true);

    actions.forEach(action => {
      const t = setTimeout(() => {
        if (action.x !== undefined && action.y !== undefined) {
          setCursorPos({ x: action.x, y: action.y });
        }
        setCursorAction(action.label);

        if (action.type === "click" && action.x !== undefined && action.y !== undefined) {
          const id = ++rippleId.current;
          setRipples(prev => [...prev, { x: action.x!, y: action.y!, id }]);
          setTimeout(() => setRipples(prev => prev.filter(r => r.id !== id)), 600);
        }

        // Clear action label after 1.5s
        setTimeout(() => setCursorAction(undefined), 1500);
      }, action.delay);
      actionTimers.current.push(t);
    });

    // Deactivate cursor after all actions
    const maxDelay = actions.reduce((m, a) => Math.max(m, a.delay), 0) + 2000;
    const endTimer = setTimeout(() => setAgentActive(false), maxDelay);
    actionTimers.current.push(endTimer);
  }, []);

  const navigate = (idx: number) => {
    if (idx < 0 || idx >= PAGES.length) return;
    setIsLoading(true);
    setAgentActive(false);
    actionTimers.current.forEach(clearTimeout);
    setTimeout(() => {
      setPageIndex(idx);
      setUrlInput(PAGES[idx].url);
      setIsLoading(false);
      if (isRunning && PAGES[idx].agentActions?.length) {
        setTimeout(() => runAgentActions(PAGES[idx].agentActions!), 300);
      }
    }, 700);
  };

  // Auto-run actions when isRunning changes
  useEffect(() => {
    if (isRunning && page.agentActions?.length && page.status === "loaded") {
      runAgentActions(page.agentActions);
    } else if (!isRunning) {
      setAgentActive(false);
      actionTimers.current.forEach(clearTimeout);
    }
  }, [isRunning, page, runAgentActions]);

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Find matching page or stay on current
    const match = PAGES.findIndex(p => p.url.includes(urlInput.replace("https://", "").split("/")[0]));
    if (match >= 0) navigate(match);
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#0f1117]">
      {/* Browser chrome */}
      <div className="shrink-0 border-b border-gray-100 dark:border-[#2a2d3a] bg-[#f3f4f6] dark:bg-[#1a1d2e] px-2 py-1.5 space-y-1.5">
        {/* Nav + URL bar */}
        <div className="flex items-center gap-1">
          {/* Traffic lights */}
          <div className="flex items-center gap-1 mr-1">
            <div className="w-2.5 h-2.5 rounded-full bg-red-400" />
            <div className="w-2.5 h-2.5 rounded-full bg-amber-400" />
            <div className="w-2.5 h-2.5 rounded-full bg-green-400" />
          </div>

          <button
            onClick={() => navigate(pageIndex - 1)}
            disabled={pageIndex === 0}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] disabled:opacity-30 transition-colors"
          >
            <ArrowLeft size={11} className="text-gray-600 dark:text-gray-400" />
          </button>
          <button
            onClick={() => navigate(pageIndex + 1)}
            disabled={pageIndex === PAGES.length - 1}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] disabled:opacity-30 transition-colors"
          >
            <ArrowRight size={11} className="text-gray-600 dark:text-gray-400" />
          </button>
          <button
            onClick={() => navigate(pageIndex)}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
          >
            <RefreshCw size={11} className={cn("text-gray-600 dark:text-gray-400", isLoading && "animate-spin")} />
          </button>

          {/* URL bar */}
          <form onSubmit={handleUrlSubmit} className="flex-1">
            <div className="flex items-center gap-1.5 bg-white dark:bg-[#0f1117] border border-gray-200 dark:border-[#2a2d3a] rounded-md px-2 py-1">
              <Lock size={9} className="text-green-500 shrink-0" />
              <input
                value={urlInput}
                onChange={e => setUrlInput(e.target.value)}
                className="flex-1 text-[11px] text-gray-700 dark:text-gray-300 font-mono bg-transparent outline-none min-w-0"
              />
              {isLoading && <Loader2 size={9} className="text-indigo-500 animate-spin shrink-0" />}
            </div>
          </form>

          {/* Zoom controls */}
          <div className="flex items-center gap-0.5">
            <button
              onClick={() => setZoom(z => Math.max(50, z - 10))}
              className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
            >
              <ZoomOut size={10} className="text-gray-500" />
            </button>
            <span className="text-[9px] text-gray-400 w-7 text-center">{zoom}%</span>
            <button
              onClick={() => setZoom(z => Math.min(150, z + 10))}
              className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
            >
              <ZoomIn size={10} className="text-gray-500" />
            </button>
          </div>
        </div>

        {/* Page tabs */}
        <div className="flex items-center gap-1 overflow-x-auto pb-0.5">
          {PAGES.map((p, i) => (
            <button
              key={p.id}
              onClick={() => navigate(i)}
              className={cn(
                "flex items-center gap-1 px-2 py-1 rounded-t text-[10px] whitespace-nowrap transition-colors shrink-0 max-w-[120px]",
                i === pageIndex
                  ? "bg-white dark:bg-[#0f1117] border border-b-0 border-gray-200 dark:border-[#2a2d3a] text-gray-800 dark:text-gray-200"
                  : "text-gray-500 hover:bg-gray-200 dark:hover:bg-[#2a2d3a]"
              )}
            >
              <Globe size={8} className="shrink-0" />
              <span className="truncate">{p.title}</span>
              {i === pageIndex && p.status === "loading" && (
                <Loader2 size={8} className="animate-spin text-indigo-500 shrink-0" />
              )}
            </button>
          ))}
          <button className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors shrink-0">
            <Plus size={10} className="text-gray-400" />
          </button>
        </div>
      </div>

      {/* Agent status bar */}
      <AnimatePresence>
        {agentActive && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="shrink-0 bg-indigo-50 dark:bg-indigo-950/30 border-b border-indigo-100 dark:border-indigo-900/50 px-3 py-1.5 flex items-center gap-2 overflow-hidden"
          >
            <div className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
            <span className="text-[11px] text-indigo-700 dark:text-indigo-400 font-medium">
              {cursorAction ?? "Агент управляет браузером"}
            </span>
            <div className="ml-auto flex items-center gap-1">
              <Eye size={10} className="text-indigo-400" />
              <span className="text-[10px] text-indigo-400">ARCANE видит страницу</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Page viewport */}
      <div className="flex-1 overflow-hidden relative">
        {isLoading ? (
          <div className="flex items-center justify-center h-full bg-white dark:bg-[#0f1117]">
            <div className="flex flex-col items-center gap-3">
              <div className="relative">
                <Globe size={28} className="text-gray-200 dark:text-gray-700" />
                <Loader2 size={14} className="text-indigo-500 animate-spin absolute -bottom-1 -right-1" />
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">Загрузка страницы...</div>
              <div className="w-40 h-1 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-indigo-500 rounded-full"
                  initial={{ width: "0%" }}
                  animate={{ width: "100%" }}
                  transition={{ duration: 0.7, ease: "easeInOut" }}
                />
              </div>
            </div>
          </div>
        ) : page.status === "loading" || !page.html ? (
          <div className="flex items-center justify-center h-full bg-white dark:bg-[#0f1117]">
            <div className="flex flex-col items-center gap-2 text-center px-4">
              <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-950/50 flex items-center justify-center">
                <Globe size={18} className="text-indigo-400" />
              </div>
              <div className="text-xs font-medium text-gray-700 dark:text-gray-300">Агент открывает страницу</div>
              <div className="text-[11px] text-gray-400 font-mono">{page.url}</div>
              <div className="flex items-center gap-1.5 mt-1">
                <Loader2 size={11} className="text-indigo-400 animate-spin" />
                <span className="text-[11px] text-gray-400">Ожидание ответа сервера...</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="relative h-full overflow-auto">
            {/* Zoom wrapper */}
            <div
              style={{ transform: `scale(${zoom / 100})`, transformOrigin: "top left", width: `${10000 / zoom}%` }}
            >
              <div
                className="min-h-full"
                dangerouslySetInnerHTML={{ __html: page.html }}
              />
            </div>

            {/* Agent cursor overlay */}
            {agentActive && (
              <div className="absolute inset-0 pointer-events-none">
                <AnimatePresence>
                  {cursorAction !== undefined && (
                    <AgentCursor pos={cursorPos} action={cursorAction} />
                  )}
                  {!cursorAction && agentActive && (
                    <AgentCursor pos={cursorPos} />
                  )}
                </AnimatePresence>

                {/* Click ripples */}
                {ripples.map(r => (
                  <ClickRipple key={r.id} x={r.x} y={r.y} id={r.id} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="shrink-0 border-t border-gray-100 dark:border-[#2a2d3a] bg-[#f3f4f6] dark:bg-[#1a1d2e] px-3 py-1 flex items-center gap-3">
        <div className={cn(
          "flex items-center gap-1 text-[10px] font-medium",
          isLoading ? "text-amber-600" :
          page.status === "loaded" ? "text-green-600" : "text-gray-400"
        )}>
          <div className={cn(
            "w-1.5 h-1.5 rounded-full",
            isLoading ? "bg-amber-400 animate-pulse" :
            page.status === "loaded" ? "bg-green-400" : "bg-gray-300"
          )} />
          {isLoading ? "Загрузка..." : page.status === "loaded" ? "Готово" : "Ожидание..."}
        </div>
        <span className="text-[10px] text-gray-400 ml-auto">
          Вкладка {pageIndex + 1} из {PAGES.length}
        </span>
        <button className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors">
          <ExternalLink size={10} className="text-gray-400" />
        </button>
      </div>
    </div>
  );
}

// ─── Browser Offline / Permission Denied Overlay ─────────────────────────────

interface BrowserOfflineOverlayProps {
  reason: BrowserOfflineReason;
  onRetry?: () => void;
}

function BrowserOfflineOverlay({ reason, onRetry }: BrowserOfflineOverlayProps) {
  const [retrying, setRetrying] = useState(false);

  const handleRetry = () => {
    if (!onRetry) return;
    setRetrying(true);
    setTimeout(() => {
      setRetrying(false);
      onRetry();
    }, 1500);
  };

  const config = {
    sandbox_unavailable: {
      icon: <WifiOff size={32} className="text-gray-400" />,
      iconBg: "bg-gray-100 dark:bg-gray-800",
      title: "Браузер агента недоступен",
      description: "Изолированная среда выполнения (sandbox) не отвечает. Агент не может управлять браузером.",
      badge: "Sandbox offline",
      badgeColor: "bg-red-100 dark:bg-red-950/50 text-red-600 dark:text-red-400",
      showRetry: true,
    },
    permission_denied: {
      icon: <ShieldOff size={32} className="text-indigo-400" />,
      iconBg: "bg-indigo-50 dark:bg-indigo-950/40",
      title: "Нет доступа к браузеру",
      description: "Администратор отключил инструмент «Browser» для вашего аккаунта. Обратитесь к администратору.",
      badge: "Инструмент отключён",
      badgeColor: "bg-indigo-100 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400",
      showRetry: false,
    },
    reconnecting: {
      icon: <Loader2 size={32} className="text-amber-400 animate-spin" />,
      iconBg: "bg-amber-50 dark:bg-amber-950/40",
      title: "Переподключение к sandbox...",
      description: "Восстанавливаем соединение с изолированной средой выполнения. Это займёт несколько секунд.",
      badge: "Reconnecting",
      badgeColor: "bg-amber-100 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400",
      showRetry: false,
    },
    none: null,
  }[reason];

  if (!config) return null;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#0f1117]">
      {/* Fake browser chrome — greyed out */}
      <div className="shrink-0 border-b border-gray-100 dark:border-[#2a2d3a] bg-[#f3f4f6] dark:bg-[#1a1d2e] px-2 py-1.5 space-y-1.5 opacity-40 pointer-events-none select-none">
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-1 mr-1">
            <div className="w-2.5 h-2.5 rounded-full bg-red-300" />
            <div className="w-2.5 h-2.5 rounded-full bg-amber-300" />
            <div className="w-2.5 h-2.5 rounded-full bg-green-300" />
          </div>
          <div className="flex-1 bg-white dark:bg-[#0f1117] border border-gray-200 dark:border-[#2a2d3a] rounded-md px-2 py-1 flex items-center gap-1.5">
            <Lock size={9} className="text-gray-300" />
            <span className="text-[11px] text-gray-300 font-mono">—</span>
          </div>
        </div>
      </div>

      {/* Offline state */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex-1 flex flex-col items-center justify-center gap-4 px-6 text-center"
      >
        <div className={cn("w-16 h-16 rounded-2xl flex items-center justify-center", config.iconBg)}>
          {config.icon}
        </div>

        <div>
          <div className={cn(
            "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium mb-3",
            config.badgeColor
          )}>
            <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
            {config.badge}
          </div>
          <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100 mb-1.5">
            {config.title}
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 max-w-[260px] leading-relaxed">
            {config.description}
          </p>
        </div>

        {config.showRetry && onRetry && (
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 text-xs font-medium transition-all disabled:opacity-60"
          >
            {retrying
              ? <Loader2 size={12} className="animate-spin" />
              : <RefreshCw size={12} />
            }
            {retrying ? "Подключение..." : "Повторить попытку"}
          </button>
        )}
      </motion.div>

      {/* Status bar */}
      <div className="shrink-0 border-t border-gray-100 dark:border-[#2a2d3a] bg-[#f3f4f6] dark:bg-[#1a1d2e] px-3 py-1 flex items-center gap-3">
        <div className="flex items-center gap-1 text-[10px] font-medium text-red-500">
          <div className="w-1.5 h-1.5 rounded-full bg-red-400" />
          {reason === "reconnecting" ? "Переподключение..." : "Нет соединения"}
        </div>
        <span className="text-[10px] text-gray-400 ml-auto">ARCANE Browser</span>
      </div>
    </div>
  );
}
