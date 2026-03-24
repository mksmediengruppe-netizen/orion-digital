// ORION ScheduledTasksPanel — "Warm Intelligence" design
// Full-featured scheduled tasks page:
//   - Task list with status grouping (active / paused / failed)
//   - Create / Edit modal with visual cron builder + raw cron input
//   - Next-run preview (shows next 5 upcoming times)
//   - Enable / Disable / Run now / Delete actions
//   - Run history per task
//   - Stats bar

import { useState, useEffect, useCallback, useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  Calendar, Clock, Plus, Play, Pause, Trash2, MoreHorizontal,
  CheckCircle2, XCircle, AlertTriangle, RefreshCw, ChevronDown,
  X, ToggleLeft, ToggleRight, Pencil, History, ChevronRight,
  ChevronLeft, Info, Zap, Code2, Timer, ArrowRight, Copy,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuTrigger, DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";

// ─── Types ────────────────────────────────────────────────────────────────────

export type TaskStatus = "active" | "paused" | "running" | "failed";
export type RunResult = "success" | "failed" | "running";

export interface RunHistoryEntry {
  id: string;
  startedAt: string;
  duration: string;
  status: RunResult;
  cost: string;
  note?: string;
}

export interface ScheduledTask {
  id: string;
  title: string;
  description: string;
  prompt: string;
  cron: string;
  cronLabel: string;
  nextRuns: string[];      // pre-computed next 5 run times (human-readable)
  lastRun: string | null;
  lastStatus: RunResult | null;
  status: TaskStatus;
  runCount: number;
  avgCost: string;
  category: string;
  history: RunHistoryEntry[];
  createdAt: string;
}

// ─── Cron utilities ───────────────────────────────────────────────────────────

// Lightweight cron parser — no external deps, covers 5-field standard cron
// Returns human-readable label and next N run times (simulated for prototype)

interface CronParts {
  minute: string;
  hour: string;
  dom: string;   // day of month
  month: string;
  dow: string;   // day of week
}

function parseCron(expr: string): CronParts | null {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minute, hour, dom, month, dow] = parts;
  return { minute, hour, dom, month, dow };
}

function cronToLabel(expr: string): string {
  const p = parseCron(expr);
  if (!p) return expr;

  // Common patterns
  if (expr === "* * * * *") return "Каждую минуту";
  if (expr === "0 * * * *") return "Каждый час";
  if (p.minute !== "*" && p.hour !== "*" && p.dom === "*" && p.month === "*" && p.dow === "*") {
    return `Ежедневно в ${p.hour.padStart(2,"0")}:${p.minute.padStart(2,"0")}`;
  }
  if (p.minute !== "*" && p.hour !== "*" && p.dom === "*" && p.month === "*" && p.dow !== "*") {
    const days = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    const d = p.dow.split(",").map(n => days[parseInt(n)] ?? n).join(", ");
    return `По ${d} в ${p.hour.padStart(2,"0")}:${p.minute.padStart(2,"0")}`;
  }
  if (p.minute !== "*" && p.hour !== "*" && p.dom !== "*" && p.month === "*" && p.dow === "*") {
    return `${p.dom}-го числа в ${p.hour.padStart(2,"0")}:${p.minute.padStart(2,"0")}`;
  }
  if (p.minute.startsWith("*/")) {
    return `Каждые ${p.minute.slice(2)} мин`;
  }
  if (p.hour.startsWith("*/")) {
    return `Каждые ${p.hour.slice(2)} ч`;
  }
  return `По расписанию (${expr})`;
}

// Simulate next N run times for a given cron expression
// (In production this would be computed server-side or via a cron library)
function getNextRuns(expr: string, count = 5): string[] {
  const p = parseCron(expr);
  if (!p) return [];

  const now = new Date();
  const results: string[] = [];
  const pad = (n: number) => String(n).padStart(2, "0");
  const fmt = (d: Date) => {
    const today = new Date();
    const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
    if (d.toDateString() === today.toDateString()) return `сегодня в ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (d.toDateString() === tomorrow.toDateString()) return `завтра в ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const days = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
    return `${days[d.getDay()]} ${pad(d.getDate())}.${pad(d.getMonth()+1)} в ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  // Parse fixed values
  const minute = p.minute === "*" ? -1 : (p.minute.startsWith("*/") ? -2 : parseInt(p.minute));
  const hour   = p.hour   === "*" ? -1 : (p.hour.startsWith("*/")   ? -2 : parseInt(p.hour));
  const step_m = p.minute.startsWith("*/") ? parseInt(p.minute.slice(2)) : 0;
  const step_h = p.hour.startsWith("*/")   ? parseInt(p.hour.slice(2))   : 0;

  const cursor = new Date(now);
  cursor.setSeconds(0, 0);
  cursor.setMinutes(cursor.getMinutes() + 1); // start from next minute

  for (let i = 0; i < 500 && results.length < count; i++) {
    const m = cursor.getMinutes();
    const h = cursor.getHours();
    const dom = cursor.getDate();
    const dow = cursor.getDay();
    const mo = cursor.getMonth() + 1;

    const minuteOk = minute === -1 ? true : minute === -2 ? (m % step_m === 0) : m === minute;
    const hourOk   = hour   === -1 ? true : hour   === -2 ? (h % step_h === 0) : h === hour;
    const domOk    = p.dom   === "*" ? true : parseInt(p.dom)   === dom;
    const monthOk  = p.month === "*" ? true : parseInt(p.month) === mo;
    const dowOk    = p.dow   === "*" ? true : p.dow.split(",").map(Number).includes(dow);

    if (minuteOk && hourOk && domOk && monthOk && dowOk) {
      results.push(fmt(new Date(cursor)));
    }

    cursor.setMinutes(cursor.getMinutes() + 1);
  }

  return results;
}

// ─── Preset cron expressions ──────────────────────────────────────────────────

interface CronPreset {
  label: string;
  expr: string;
  description: string;
}

const CRON_PRESETS: CronPreset[] = [
  { label: "Каждую минуту",   expr: "* * * * *",     description: "Запускать каждую минуту" },
  { label: "Каждый час",      expr: "0 * * * *",     description: "В начале каждого часа" },
  { label: "Каждые 6 часов",  expr: "0 */6 * * *",   description: "В 00:00, 06:00, 12:00, 18:00" },
  { label: "Ежедневно 03:00", expr: "0 3 * * *",     description: "Каждый день в 03:00" },
  { label: "Ежедневно 09:00", expr: "0 9 * * *",     description: "Каждый день в 09:00" },
  { label: "Пн–Пт 09:00",    expr: "0 9 * * 1-5",   description: "По будням в 09:00" },
  { label: "Еженедельно Пн",  expr: "0 9 * * 1",     description: "Каждый понедельник в 09:00" },
  { label: "1-го числа",      expr: "0 0 1 * *",     description: "Первый день каждого месяца" },
  { label: "Каждые 15 мин",   expr: "*/15 * * * *",  description: "Каждые 15 минут" },
  { label: "Каждые 30 мин",   expr: "*/30 * * * *",  description: "Каждые 30 минут" },
];

// ─── Initial data ─────────────────────────────────────────────────────────────

const INITIAL_TASKS: ScheduledTask[] = [
  {
    id: "st1",
    title: "Мониторинг доступности серверов",
    description: "Проверка uptime всех серверов, отправка отчёта в Telegram при ошибках",
    prompt: "Проверь доступность серверов 185.22.xx.xx, 185.22.xx.xy, 185.22.xx.xz. Для каждого выполни ping и HTTP-запрос. Если хотя бы один сервер недоступен — отправь уведомление в Telegram.",
    cron: "0 * * * *",
    cronLabel: "Каждый час",
    nextRuns: getNextRuns("0 * * * *"),
    lastRun: "1 час назад",
    lastStatus: "success",
    status: "active",
    runCount: 312,
    avgCost: "$0.04",
    category: "Мониторинг",
    createdAt: "12 янв 2026",
    history: [
      { id: "h1", startedAt: "1 час назад",  duration: "12с", status: "success", cost: "$0.04" },
      { id: "h2", startedAt: "2 часа назад", duration: "11с", status: "success", cost: "$0.04" },
      { id: "h3", startedAt: "3 часа назад", duration: "14с", status: "success", cost: "$0.05" },
    ],
  },
  {
    id: "st2",
    title: "Еженедельный SEO отчёт",
    description: "Сбор позиций, анализ трафика, сравнение с прошлой неделей",
    prompt: "Собери данные о позициях сайта example.com в Google по ключевым словам из файла keywords.txt. Сравни с данными прошлой недели. Подготовь отчёт в формате Markdown и сохрани в /reports/seo/.",
    cron: "0 9 * * 5",
    cronLabel: "По пятницам в 09:00",
    nextRuns: getNextRuns("0 9 * * 5"),
    lastRun: "7 дней назад",
    lastStatus: "success",
    status: "active",
    runCount: 24,
    avgCost: "$0.85",
    category: "SEO",
    createdAt: "3 фев 2026",
    history: [
      { id: "h4", startedAt: "7 дней назад",  duration: "4м 12с", status: "success", cost: "$0.82" },
      { id: "h5", startedAt: "14 дней назад", duration: "3м 58с", status: "success", cost: "$0.88" },
    ],
  },
  {
    id: "st3",
    title: "Резервное копирование БД",
    description: "Создание дампа MySQL, загрузка на S3, проверка целостности",
    prompt: "Создай дамп базы данных production_db на сервере 185.22.xx.xx. Загрузи архив на S3 в бакет backups/mysql/. Проверь целостность архива. Удали дампы старше 30 дней.",
    cron: "0 3 * * *",
    cronLabel: "Ежедневно в 03:00",
    nextRuns: getNextRuns("0 3 * * *"),
    lastRun: "вчера в 03:00",
    lastStatus: "success",
    status: "active",
    runCount: 89,
    avgCost: "$0.12",
    category: "Бэкап",
    createdAt: "5 янв 2026",
    history: [
      { id: "h6", startedAt: "вчера 03:00",   duration: "1м 45с", status: "success", cost: "$0.12" },
      { id: "h7", startedAt: "2 дня назад",   duration: "1м 38с", status: "success", cost: "$0.11" },
      { id: "h8", startedAt: "3 дня назад",   duration: "2м 01с", status: "success", cost: "$0.14" },
    ],
  },
  {
    id: "st4",
    title: "Обновление SSL сертификатов",
    description: "Проверка срока действия, автообновление через certbot",
    prompt: "Проверь срок действия SSL сертификатов для доменов example.com, api.example.com, admin.example.com. Если до истечения осталось менее 30 дней — запусти certbot renew. Перезапусти nginx после обновления.",
    cron: "0 0 1 * *",
    cronLabel: "1-го числа каждого месяца",
    nextRuns: getNextRuns("0 0 1 * *"),
    lastRun: "1 марта",
    lastStatus: "failed",
    status: "failed",
    runCount: 3,
    avgCost: "$0.18",
    category: "Безопасность",
    createdAt: "1 янв 2026",
    history: [
      { id: "h9",  startedAt: "1 марта",  duration: "45с", status: "failed",  cost: "$0.06", note: "certbot: connection refused" },
      { id: "h10", startedAt: "1 февраля", duration: "52с", status: "success", cost: "$0.18" },
      { id: "h11", startedAt: "1 января",  duration: "48с", status: "success", cost: "$0.17" },
    ],
  },
  {
    id: "st5",
    title: "Аудит безопасности",
    description: "Сканирование уязвимостей, проверка прав доступа, обновление пакетов",
    prompt: "Выполни аудит безопасности сервера 185.22.xx.xx: проверь открытые порты, права доступа к критическим файлам, наличие обновлений безопасности для установленных пакетов. Сформируй отчёт.",
    cron: "0 0 * * 0",
    cronLabel: "По воскресеньям в 00:00",
    nextRuns: getNextRuns("0 0 * * 0"),
    lastRun: "7 дней назад",
    lastStatus: "success",
    status: "paused",
    runCount: 12,
    avgCost: "$0.65",
    category: "Безопасность",
    createdAt: "10 янв 2026",
    history: [
      { id: "h12", startedAt: "7 дней назад",  duration: "3м 22с", status: "success", cost: "$0.64" },
      { id: "h13", startedAt: "14 дней назад", duration: "3м 08с", status: "success", cost: "$0.66" },
    ],
  },
];

// ─── Category colors ──────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  "Мониторинг":  "bg-blue-50 text-blue-600 dark:bg-blue-950/40 dark:text-blue-400",
  "SEO":         "bg-violet-50 text-violet-600 dark:bg-violet-950/40 dark:text-violet-400",
  "Бэкап":       "bg-green-50 text-green-600 dark:bg-green-950/40 dark:text-green-400",
  "Безопасность":"bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400",
  "Аналитика":   "bg-pink-50 text-pink-600 dark:bg-pink-950/40 dark:text-pink-400",
  "Другое":      "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

const CATEGORIES = Object.keys(CATEGORY_COLORS);

// ─── Main Panel ───────────────────────────────────────────────────────────────

interface ScheduledTasksPanelProps {
  onClose?: () => void;
  /** External tasks from real API (overrides mock data when provided) */
  externalTasks?: ScheduledTask[];
  /** External API handlers (when provided, replace local mock handlers) */
  onToggle?: (id: string) => Promise<void>;
  onRunNow?: (id: string) => Promise<void>;
  onDelete?: (id: string) => Promise<void>;
  onSave?: (data: Omit<ScheduledTask, "id" | "runCount" | "lastRun" | "lastStatus" | "history" | "createdAt">, editingId?: string) => Promise<void>;
  apiLoading?: boolean;
  apiError?: string | null;
}

export function ScheduledTasksPanel({
  onClose,
  externalTasks,
  onToggle,
  onRunNow,
  onDelete,
  onSave,
  apiLoading = false,
  apiError = null,
}: ScheduledTasksPanelProps) {
  const [localTasks, setLocalTasks] = useState<ScheduledTask[]>(INITIAL_TASKS);
  // Use external tasks when provided (real API mode), otherwise use local mock
  const tasks = externalTasks ?? localTasks;
  const setTasks = (updater: ((prev: ScheduledTask[]) => ScheduledTask[]) | ScheduledTask[]) => {
    if (!externalTasks) {
      setLocalTasks(updater as ((prev: ScheduledTask[]) => ScheduledTask[]));
    }
  };
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [detailTask, setDetailTask] = useState<ScheduledTask | null>(null);
  const [filter, setFilter] = useState<"all" | "active" | "paused" | "failed">("all");

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (isCreating || editingTask) { setIsCreating(false); setEditingTask(null); }
        else if (detailTask) setDetailTask(null);
        else onClose?.();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose, isCreating, editingTask, detailTask]);

  const toggleTask = async (id: string) => {
    if (onToggle) {
      try {
        await onToggle(id);
        const t = tasks.find(x => x.id === id);
        const next = (t?.status === "active" || t?.status === "running") ? "paused" : "active";
        toast.success(next === "active" ? `«${t?.title}» возобновлено` : `«${t?.title}» приостановлено`);
      } catch (e: unknown) {
        toast.error(`Ошибка: ${e instanceof Error ? e.message : String(e)}`);
      }
      return;
    }
    setTasks(prev => prev.map(t => {
      if (t.id !== id) return t;
      const next = (t.status === "active" || t.status === "running") ? "paused" : "active";
      toast.success(next === "active" ? `«${t.title}» возобновлено` : `«${t.title}» приостановлено`);
      return { ...t, status: next };
    }));
  };

  const runNow = async (id: string) => {
    const t = tasks.find(t => t.id === id);
    if (!t) return;
    if (onRunNow) {
      try {
        toast.success(`Запускаю «${t.title}»...`);
        await onRunNow(id);
      } catch (e: unknown) {
        toast.error(`Ошибка: ${e instanceof Error ? e.message : String(e)}`);
      }
      return;
    }
    setTasks(prev => prev.map(x => x.id === id ? { ...x, status: "running" } : x));
    toast.success(`Запускаю «${t.title}»...`);
    setTimeout(() => {
      setTasks(prev => prev.map(x => {
        if (x.id !== id) return x;
        const entry: RunHistoryEntry = {
          id: `h${Date.now()}`,
          startedAt: "только что",
          duration: `${Math.floor(Math.random() * 120 + 10)}с`,
          status: "success",
          cost: `$${(Math.random() * 0.5 + 0.05).toFixed(2)}`,
        };
        return {
          ...x,
          status: "active",
          lastRun: "только что",
          lastStatus: "success",
          runCount: x.runCount + 1,
          history: [entry, ...x.history],
        };
      }));
      toast.success(`«${t.title}» выполнено`);
    }, 3000);
  };

  const deleteTask = async (id: string) => {
    if (onDelete) {
      try {
        await onDelete(id);
        if (detailTask?.id === id) setDetailTask(null);
        toast.success("Задача удалена");
      } catch (e: unknown) {
        toast.error(`Ошибка: ${e instanceof Error ? e.message : String(e)}`);
      }
      return;
    }
    setTasks(prev => prev.filter(t => t.id !== id));
    if (detailTask?.id === id) setDetailTask(null);
    toast.success("Задача удалена");
  };

  const saveTask = async (data: Omit<ScheduledTask, "id" | "runCount" | "lastRun" | "lastStatus" | "history" | "createdAt">) => {
    if (onSave) {
      try {
        await onSave(data, editingTask?.id);
        toast.success(editingTask ? "Задача обновлена" : "Задача создана");
      } catch (e: unknown) {
        toast.error(`Ошибка: ${e instanceof Error ? e.message : String(e)}`);
      }
      setEditingTask(null);
      setIsCreating(false);
      return;
    }
    if (editingTask) {
      setTasks(prev => prev.map(t => t.id === editingTask.id ? { ...t, ...data } : t));
      if (detailTask?.id === editingTask.id) setDetailTask(prev => prev ? { ...prev, ...data } : null);
      toast.success("Задача обновлена");
    } else {
      const newTask: ScheduledTask = {
        ...data,
        id: `st${Date.now()}`,
        runCount: 0,
        lastRun: null,
        lastStatus: null,
        history: [],
        createdAt: new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" }),
      };
      setTasks(prev => [newTask, ...prev]);
      toast.success("Задача создана");
    }
    setEditingTask(null);
    setIsCreating(false);
  };

  const duplicateTask = (id: string) => {
    const t = tasks.find(x => x.id === id);
    if (!t) return;
    const copy: ScheduledTask = {
      ...t,
      id: `st${Date.now()}`,
      title: `${t.title} (копия)`,
      status: "paused",
      runCount: 0,
      lastRun: null,
      lastStatus: null,
      history: [],
      createdAt: new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" }),
    };
    setTasks(prev => [copy, ...prev]);
    toast.success("Задача скопирована");
  };

  const filtered = useMemo(() => {
    if (filter === "all") return tasks;
    if (filter === "active") return tasks.filter(t => t.status === "active" || t.status === "running");
    return tasks.filter(t => t.status === filter);
  }, [tasks, filter]);

  const counts = useMemo(() => ({
    all:    tasks.length,
    active: tasks.filter(t => t.status === "active" || t.status === "running").length,
    paused: tasks.filter(t => t.status === "paused").length,
    failed: tasks.filter(t => t.status === "failed").length,
  }), [tasks]);

  const totalCost = useMemo(() => {
    const sum = tasks.reduce((acc, t) => {
      const c = parseFloat(t.avgCost.replace("$", "")) * t.runCount;
      return acc + c;
    }, 0);
    return `$${sum.toFixed(2)}`;
  }, [tasks]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#0f1117]">
      {/* Header */}
      <div className="h-14 border-b border-[#E8E6E1] dark:border-[#2a2d3a] flex items-center px-4 gap-3 shrink-0">
        {detailTask ? (
          <>
            <button
              onClick={() => setDetailTask(null)}
              className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <ChevronLeft size={15} />
            </button>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">{detailTask.title}</div>
              <div className="text-xs text-gray-400">{detailTask.cronLabel}</div>
            </div>
            <button
              onClick={() => { setEditingTask(detailTask); setDetailTask(null); }}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 dark:hover:bg-indigo-900/40 transition-colors"
            >
              <Pencil size={11} />
              Изменить
            </button>
          </>
        ) : (
          <>
            <Calendar size={15} className="text-indigo-500 shrink-0" />
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100 flex-1">Расписание</span>
            <button
              onClick={() => setIsCreating(true)}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
            >
              <Plus size={11} />
              Новая задача
            </button>
            {onClose && (
              <button onClick={onClose} className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
                <X size={14} />
              </button>
            )}
          </>
        )}
      </div>

      {/* Detail view */}
      <AnimatePresence mode="wait">
        {detailTask ? (
          <motion.div
            key="detail"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.2 }}
            className="flex-1 overflow-y-auto"
          >
            <TaskDetailView
              task={detailTask}
              onToggle={() => { toggleTask(detailTask.id); setDetailTask(prev => prev ? { ...prev, status: prev.status === "active" ? "paused" : "active" } : null); }}
              onRunNow={() => runNow(detailTask.id)}
              onDelete={() => deleteTask(detailTask.id)}
              onDuplicate={() => duplicateTask(detailTask.id)}
            />
          </motion.div>
        ) : (
          <motion.div
            key="list"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex flex-col flex-1 overflow-hidden"
          >
            {/* Stats bar */}
            <div className="grid grid-cols-4 border-b border-[#E8E6E1] dark:border-[#2a2d3a] shrink-0">
              {[
                { key: "all",    label: "Всего",    value: counts.all,    color: "text-gray-800 dark:text-gray-100" },
                { key: "active", label: "Активных", value: counts.active, color: "text-green-600 dark:text-green-400" },
                { key: "paused", label: "Пауза",    value: counts.paused, color: "text-amber-500" },
                { key: "failed", label: "Ошибок",   value: counts.failed, color: "text-red-500" },
              ].map(s => (
                <button
                  key={s.key}
                  onClick={() => setFilter(s.key as typeof filter)}
                  className={cn(
                    "py-2.5 text-center border-r last:border-r-0 border-[#E8E6E1] dark:border-[#2a2d3a] transition-colors",
                    filter === s.key ? "bg-indigo-50 dark:bg-indigo-950/30" : "hover:bg-gray-50 dark:hover:bg-gray-800/30"
                  )}
                >
                  <div className={cn("text-base font-bold", s.color)}>{s.value}</div>
                  <div className="text-[10px] text-gray-400">{s.label}</div>
                </button>
              ))}
            </div>

            {/* Total cost strip */}
            <div className="flex items-center gap-2 px-4 py-2 border-b border-[#E8E6E1] dark:border-[#2a2d3a] bg-gray-50 dark:bg-gray-900/50 shrink-0">
              <Zap size={11} className="text-amber-500" />
              <span className="text-xs text-gray-500 dark:text-gray-400">Суммарные расходы: <span className="font-semibold text-gray-700 dark:text-gray-300">{totalCost}</span></span>
              <span className="text-gray-300 dark:text-gray-700 mx-1">·</span>
              <span className="text-xs text-gray-500 dark:text-gray-400">{tasks.reduce((a, t) => a + t.runCount, 0)} запусков</span>
            </div>

            {/* Task list */}
            <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
              {filtered.length === 0 && (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <Calendar size={32} className="text-gray-200 dark:text-gray-700 mb-3" />
                  <div className="text-sm font-medium text-gray-400">Нет задач</div>
                  <div className="text-xs text-gray-300 dark:text-gray-600 mt-1">
                    {filter === "all" ? "Создайте первую задачу по расписанию" : `Нет задач со статусом «${filter}»`}
                  </div>
                </div>
              )}
              {filtered.map(t => (
                <TaskCard
                  key={t.id}
                  task={t}
                  onToggle={() => toggleTask(t.id)}
                  onRunNow={() => runNow(t.id)}
                  onDelete={() => deleteTask(t.id)}
                  onEdit={() => setEditingTask(t)}
                  onDetail={() => setDetailTask(t)}
                  onDuplicate={() => duplicateTask(t.id)}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Create / Edit Modal */}
      <TaskFormModal
        open={isCreating || !!editingTask}
        task={editingTask}
        onClose={() => { setIsCreating(false); setEditingTask(null); }}
        onSave={saveTask}
      />
    </div>
  );
}

// ─── Task Card ────────────────────────────────────────────────────────────────

function TaskCard({ task: t, onToggle, onRunNow, onDelete, onEdit, onDetail, onDuplicate }: {
  task: ScheduledTask;
  onToggle: () => void;
  onRunNow: () => void;
  onDelete: () => void;
  onEdit: () => void;
  onDetail: () => void;
  onDuplicate: () => void;
}) {
  const isActive  = t.status === "active";
  const isRunning = t.status === "running";
  const isFailed  = t.status === "failed";
  const isPaused  = t.status === "paused";

  return (
    <div
      className={cn(
        "rounded-xl border px-3 py-2.5 transition-all cursor-pointer group",
        isFailed  ? "border-red-200 dark:border-red-900/60 bg-red-50/30 dark:bg-red-950/10 hover:border-red-300" :
        isRunning ? "border-indigo-300 dark:border-indigo-700 bg-indigo-50/30 dark:bg-indigo-950/10" :
        isPaused  ? "border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-900/30 hover:border-gray-300 opacity-70" :
                    "border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-transparent hover:border-indigo-200 dark:hover:border-indigo-800"
      )}
      onClick={onDetail}
    >
      <div className="flex items-start gap-2">
        {/* Status dot */}
        <div className="mt-1 shrink-0">
          {isRunning && <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />}
          {isActive  && <div className="w-2 h-2 rounded-full bg-green-500" />}
          {isPaused  && <div className="w-2 h-2 rounded-full bg-gray-300 dark:bg-gray-600" />}
          {isFailed  && <div className="w-2 h-2 rounded-full bg-red-500" />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-semibold text-gray-800 dark:text-gray-100 truncate">{t.title}</span>
            <span className={cn(
              "text-[9px] px-1.5 py-0.5 rounded-full font-medium shrink-0",
              CATEGORY_COLORS[t.category] ?? CATEGORY_COLORS["Другое"]
            )}>
              {t.category}
            </span>
          </div>
          <div className="text-[10px] text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-1">{t.description}</div>

          <div className="flex items-center gap-2.5 mt-1.5 flex-wrap">
            {/* Cron label */}
            <div className="flex items-center gap-1">
              <Clock size={9} className="text-gray-400" />
              <span className="text-[10px] text-gray-500 dark:text-gray-400 font-mono">{t.cronLabel}</span>
            </div>
            {/* Next run */}
            {(isActive || isRunning) && t.nextRuns[0] && (
              <div className="flex items-center gap-1">
                <ArrowRight size={9} className="text-indigo-400" />
                <span className="text-[10px] text-indigo-500 dark:text-indigo-400">{t.nextRuns[0]}</span>
              </div>
            )}
            {/* Last run status */}
            {t.lastStatus === "success" && (
              <div className="flex items-center gap-1">
                <CheckCircle2 size={9} className="text-green-500" />
                <span className="text-[10px] text-gray-400">{t.lastRun}</span>
              </div>
            )}
            {t.lastStatus === "failed" && (
              <div className="flex items-center gap-1">
                <XCircle size={9} className="text-red-500" />
                <span className="text-[10px] text-red-400">{t.lastRun} — ошибка</span>
              </div>
            )}
            {/* Cost */}
            <span className="text-[10px] text-gray-400 font-mono">{t.avgCost}/запуск</span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-0.5 shrink-0" onClick={e => e.stopPropagation()}>
          <button
            onClick={onToggle}
            className={cn(
              "p-1 rounded transition-colors",
              isActive || isRunning ? "text-green-500 hover:bg-green-50 dark:hover:bg-green-950/30" : "text-gray-300 dark:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800"
            )}
            title={isActive ? "Приостановить" : "Возобновить"}
          >
            {isActive || isRunning ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
          </button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors opacity-0 group-hover:opacity-100">
                <MoreHorizontal size={12} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44 text-xs">
              <DropdownMenuItem onClick={onRunNow} className="gap-2 text-xs">
                <Play size={11} />
                Запустить сейчас
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onEdit} className="gap-2 text-xs">
                <Pencil size={11} />
                Изменить
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onDuplicate} className="gap-2 text-xs">
                <Copy size={11} />
                Дублировать
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onToggle} className="gap-2 text-xs">
                {isActive ? <Pause size={11} /> : <Play size={11} />}
                {isActive ? "Приостановить" : "Возобновить"}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onDelete} className="gap-2 text-xs text-red-600 focus:text-red-600 focus:bg-red-50 dark:focus:bg-red-950/30">
                <Trash2 size={11} />
                Удалить
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  );
}

// ─── Task Detail View ─────────────────────────────────────────────────────────

function TaskDetailView({ task: t, onToggle, onRunNow, onDelete, onDuplicate }: {
  task: ScheduledTask;
  onToggle: () => void;
  onRunNow: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
}) {
  const isActive = t.status === "active" || t.status === "running";

  return (
    <div className="p-4 space-y-4">
      {/* Status + actions */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className={cn(
          "flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border",
          t.status === "active"  ? "bg-green-50 dark:bg-green-950/40 text-green-700 dark:text-green-400 border-green-200 dark:border-green-800" :
          t.status === "running" ? "bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-400 border-indigo-200 dark:border-indigo-800" :
          t.status === "failed"  ? "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800" :
                                   "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700"
        )}>
          <div className={cn("w-1.5 h-1.5 rounded-full",
            t.status === "active"  ? "bg-green-500" :
            t.status === "running" ? "bg-indigo-500 animate-pulse" :
            t.status === "failed"  ? "bg-red-500" : "bg-gray-400"
          )} />
          {t.status === "active" ? "Активна" : t.status === "running" ? "Выполняется" : t.status === "failed" ? "Ошибка" : "Пауза"}
        </span>
        <span className={cn(
          "text-xs px-2 py-1 rounded-full font-medium",
          CATEGORY_COLORS[t.category] ?? CATEGORY_COLORS["Другое"]
        )}>
          {t.category}
        </span>
        <div className="flex-1" />
        <button
          onClick={onRunNow}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
        >
          <Play size={11} />
          Запустить
        </button>
        <button
          onClick={onToggle}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-[#E8E6E1] dark:border-[#2a2d3a] text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          {isActive ? <Pause size={11} /> : <Play size={11} />}
          {isActive ? "Пауза" : "Возобновить"}
        </button>
      </div>

      {/* Cron + next runs */}
      <div className="rounded-xl border border-[#E8E6E1] dark:border-[#2a2d3a] overflow-hidden">
        <div className="px-3 py-2 bg-gray-50 dark:bg-gray-900/50 border-b border-[#E8E6E1] dark:border-[#2a2d3a] flex items-center gap-2">
          <Timer size={12} className="text-indigo-500" />
          <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">Расписание</span>
        </div>
        <div className="p-3 space-y-2">
          <div className="flex items-center gap-2">
            <code className="text-xs font-mono bg-gray-100 dark:bg-gray-800 px-2 py-1 rounded text-gray-700 dark:text-gray-300">{t.cron}</code>
            <span className="text-xs text-gray-500 dark:text-gray-400">{t.cronLabel}</span>
          </div>
          {t.nextRuns.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Следующие запуски</div>
              <div className="space-y-1">
                {t.nextRuns.slice(0, 5).map((run, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <div className={cn(
                      "w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0",
                      i === 0 ? "bg-indigo-100 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400" : "bg-gray-100 dark:bg-gray-800 text-gray-400"
                    )}>
                      {i + 1}
                    </div>
                    <span className={cn("text-xs", i === 0 ? "text-indigo-600 dark:text-indigo-400 font-medium" : "text-gray-500 dark:text-gray-400")}>
                      {run}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Prompt */}
      <div className="rounded-xl border border-[#E8E6E1] dark:border-[#2a2d3a] overflow-hidden">
        <div className="px-3 py-2 bg-gray-50 dark:bg-gray-900/50 border-b border-[#E8E6E1] dark:border-[#2a2d3a] flex items-center gap-2">
          <Code2 size={12} className="text-indigo-500" />
          <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">Промпт задачи</span>
        </div>
        <div className="p-3">
          <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed whitespace-pre-wrap">{t.prompt}</p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "Запусков",   value: t.runCount.toString() },
          { label: "Ср. стоимость", value: t.avgCost },
          { label: "Создана",    value: t.createdAt },
        ].map(s => (
          <div key={s.label} className="rounded-xl border border-[#E8E6E1] dark:border-[#2a2d3a] p-2.5 text-center">
            <div className="text-sm font-bold text-gray-800 dark:text-gray-100">{s.value}</div>
            <div className="text-[10px] text-gray-400 mt-0.5">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Run history */}
      <div className="rounded-xl border border-[#E8E6E1] dark:border-[#2a2d3a] overflow-hidden">
        <div className="px-3 py-2 bg-gray-50 dark:bg-gray-900/50 border-b border-[#E8E6E1] dark:border-[#2a2d3a] flex items-center gap-2">
          <History size={12} className="text-indigo-500" />
          <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">История запусков</span>
        </div>
        {t.history.length === 0 ? (
          <div className="p-4 text-center text-xs text-gray-400">Ещё не запускалась</div>
        ) : (
          <div className="divide-y divide-[#E8E6E1] dark:divide-[#2a2d3a]">
            {t.history.map(h => (
              <div key={h.id} className="flex items-center gap-3 px-3 py-2">
                {h.status === "success" && <CheckCircle2 size={12} className="text-green-500 shrink-0" />}
                {h.status === "failed"  && <XCircle size={12} className="text-red-500 shrink-0" />}
                {h.status === "running" && <RefreshCw size={12} className="text-indigo-500 animate-spin shrink-0" />}
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-gray-700 dark:text-gray-300">{h.startedAt}</div>
                  {h.note && <div className="text-[10px] text-red-500 mt-0.5">{h.note}</div>}
                </div>
                <div className="text-[10px] text-gray-400 font-mono shrink-0">{h.duration}</div>
                <div className="text-[10px] text-gray-400 font-mono shrink-0">{h.cost}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Danger zone */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={onDuplicate}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-[#E8E6E1] dark:border-[#2a2d3a] text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          <Copy size={11} />
          Дублировать
        </button>
        <button
          onClick={onDelete}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors ml-auto"
        >
          <Trash2 size={11} />
          Удалить задачу
        </button>
      </div>
    </div>
  );
}

// ─── Task Form Modal ──────────────────────────────────────────────────────────

interface TaskFormData {
  title: string;
  description: string;
  prompt: string;
  cron: string;
  cronLabel: string;
  nextRuns: string[];
  status: TaskStatus;
  avgCost: string;
  category: string;
}

function TaskFormModal({ open, task, onClose, onSave }: {
  open: boolean;
  task: ScheduledTask | null;
  onClose: () => void;
  onSave: (data: Omit<ScheduledTask, "id" | "runCount" | "lastRun" | "lastStatus" | "history" | "createdAt">) => void;
}) {
  const [form, setForm] = useState<TaskFormData>({
    title: "",
    description: "",
    prompt: "",
    cron: "0 9 * * *",
    cronLabel: "Ежедневно в 09:00",
    nextRuns: [],
    status: "active",
    avgCost: "$0.10",
    category: "Другое",
  });
  const [cronMode, setCronMode] = useState<"preset" | "visual" | "raw">("preset");
  const [cronError, setCronError] = useState("");

  // Reset form when modal opens
  useEffect(() => {
    if (!open) return;
    if (task) {
      setForm({
        title: task.title,
        description: task.description,
        prompt: task.prompt,
        cron: task.cron,
        cronLabel: task.cronLabel,
        nextRuns: task.nextRuns,
        status: task.status,
        avgCost: task.avgCost,
        category: task.category,
      });
    } else {
      setForm({
        title: "",
        description: "",
        prompt: "",
        cron: "0 9 * * *",
        cronLabel: cronToLabel("0 9 * * *"),
        nextRuns: getNextRuns("0 9 * * *"),
        status: "active",
        avgCost: "$0.10",
        category: "Другое",
      });
    }
    setCronMode("preset");
    setCronError("");
  }, [open, task]);

  const applyCron = (expr: string) => {
    const p = parseCron(expr);
    if (!p) {
      setCronError("Неверный формат cron. Ожидается 5 полей: мин час день месяц день_недели");
      return;
    }
    setCronError("");
    setForm(f => ({
      ...f,
      cron: expr,
      cronLabel: cronToLabel(expr),
      nextRuns: getNextRuns(expr),
    }));
  };

  const handleSubmit = () => {
    if (!form.title.trim()) { toast.error("Введите название задачи"); return; }
    if (!form.prompt.trim()) { toast.error("Введите промпт задачи"); return; }
    if (!parseCron(form.cron)) { toast.error("Неверное cron-выражение"); return; }
    onSave(form);
  };

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose(); }}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto p-0 gap-0">
        <DialogHeader className="px-5 pt-5 pb-4 border-b border-[#E8E6E1] dark:border-[#2a2d3a]">
          <DialogTitle className="text-base font-semibold text-gray-900 dark:text-gray-100">
            {task ? "Изменить задачу" : "Новая задача по расписанию"}
          </DialogTitle>
        </DialogHeader>

        <div className="p-5 space-y-5">
          {/* Title + Category */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 space-y-1.5">
              <label className="text-xs font-semibold text-gray-600 dark:text-gray-400">Название</label>
              <input
                className="w-full px-3 py-2 rounded-lg border border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-gray-900 text-sm text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400"
                placeholder="Мониторинг серверов"
                value={form.title}
                onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-gray-600 dark:text-gray-400">Категория</label>
              <select
                className="w-full px-3 py-2 rounded-lg border border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-gray-900 text-sm text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400"
                value={form.category}
                onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
              >
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-gray-600 dark:text-gray-400">Краткое описание</label>
            <input
              className="w-full px-3 py-2 rounded-lg border border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-gray-900 text-sm text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400"
              placeholder="Что делает эта задача"
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            />
          </div>

          {/* Prompt */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-gray-600 dark:text-gray-400">Промпт для агента</label>
            <textarea
              rows={4}
              className="w-full px-3 py-2 rounded-lg border border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-gray-900 text-sm text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-400 resize-none"
              placeholder="Опишите задачу для агента подробно. Например: Проверь доступность сервера 185.22.xx.xx, выполни ping и HTTP-запрос, если недоступен — отправь уведомление."
              value={form.prompt}
              onChange={e => setForm(f => ({ ...f, prompt: e.target.value }))}
            />
          </div>

          {/* Cron builder */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-gray-600 dark:text-gray-400">Расписание</label>
              <div className="flex rounded-lg border border-[#E8E6E1] dark:border-[#2a2d3a] overflow-hidden text-xs">
                {(["preset", "visual", "raw"] as const).map(m => (
                  <button
                    key={m}
                    onClick={() => setCronMode(m)}
                    className={cn(
                      "px-2.5 py-1 transition-colors",
                      cronMode === m
                        ? "bg-indigo-600 text-white"
                        : "text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
                    )}
                  >
                    {m === "preset" ? "Шаблоны" : m === "visual" ? "Конструктор" : "Cron"}
                  </button>
                ))}
              </div>
            </div>

            {/* Preset picker */}
            {cronMode === "preset" && (
              <div className="grid grid-cols-2 gap-1.5">
                {CRON_PRESETS.map(p => (
                  <button
                    key={p.expr}
                    onClick={() => applyCron(p.expr)}
                    className={cn(
                      "text-left px-3 py-2 rounded-lg border text-xs transition-all",
                      form.cron === p.expr
                        ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300"
                        : "border-[#E8E6E1] dark:border-[#2a2d3a] hover:border-indigo-200 dark:hover:border-indigo-800 text-gray-700 dark:text-gray-300"
                    )}
                  >
                    <div className="font-medium">{p.label}</div>
                    <div className="text-[10px] text-gray-400 mt-0.5">{p.description}</div>
                  </button>
                ))}
              </div>
            )}

            {/* Visual builder */}
            {cronMode === "visual" && (
              <CronVisualBuilder cron={form.cron} onChange={applyCron} />
            )}

            {/* Raw cron */}
            {cronMode === "raw" && (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <input
                    className={cn(
                      "flex-1 px-3 py-2 rounded-lg border font-mono text-sm bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/30",
                      cronError ? "border-red-400" : "border-[#E8E6E1] dark:border-[#2a2d3a] focus:border-indigo-400"
                    )}
                    placeholder="* * * * *"
                    value={form.cron}
                    onChange={e => {
                      setForm(f => ({ ...f, cron: e.target.value }));
                      if (parseCron(e.target.value)) applyCron(e.target.value);
                      else setCronError("Неверный формат");
                    }}
                  />
                </div>
                {cronError && <div className="text-xs text-red-500">{cronError}</div>}
                <div className="text-xs text-gray-400 font-mono">
                  <span className="text-gray-500">Формат:</span> минуты(0-59) часы(0-23) день(1-31) месяц(1-12) день_недели(0-6)
                </div>
              </div>
            )}

            {/* Preview */}
            {!cronError && form.nextRuns.length > 0 && (
              <div className="rounded-lg bg-gray-50 dark:bg-gray-900/50 border border-[#E8E6E1] dark:border-[#2a2d3a] px-3 py-2.5">
                <div className="flex items-center gap-1.5 mb-2">
                  <ArrowRight size={11} className="text-indigo-500" />
                  <span className="text-xs font-semibold text-gray-600 dark:text-gray-400">Следующие запуски</span>
                  <span className="text-xs text-gray-400 ml-1">({form.cronLabel})</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {form.nextRuns.slice(0, 5).map((r, i) => (
                    <span key={i} className={cn(
                      "text-xs px-2 py-0.5 rounded-full",
                      i === 0
                        ? "bg-indigo-100 dark:bg-indigo-950/50 text-indigo-700 dark:text-indigo-300 font-medium"
                        : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
                    )}>
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="px-5 py-4 border-t border-[#E8E6E1] dark:border-[#2a2d3a] flex gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-[#E8E6E1] dark:border-[#2a2d3a] text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Отмена
          </button>
          <button
            onClick={handleSubmit}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
          >
            {task ? "Сохранить изменения" : "Создать задачу"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Visual Cron Builder ──────────────────────────────────────────────────────

function CronVisualBuilder({ cron, onChange }: { cron: string; onChange: (expr: string) => void }) {
  const parsed = parseCron(cron) ?? { minute: "0", hour: "9", dom: "*", month: "*", dow: "*" };

  const [minute, setMinute] = useState(parsed.minute);
  const [hour,   setHour]   = useState(parsed.hour);
  const [dom,    setDom]    = useState(parsed.dom);
  const [month,  setMonth]  = useState(parsed.month);
  const [dow,    setDow]    = useState(parsed.dow);

  const [minuteMode, setMinuteMode] = useState<"fixed" | "every">(parsed.minute.startsWith("*/") ? "every" : "fixed");
  const [hourMode,   setHourMode]   = useState<"fixed" | "every">(parsed.hour.startsWith("*/") ? "every" : "fixed");

  const DOW_LABELS = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"];
  const MONTH_LABELS = ["Янв","Фев","Мар","Апр","Май","Июн","Июл","Авг","Сен","Окт","Ноя","Дек"];

  const selectedDows = useMemo(() => {
    if (dow === "*") return new Set<number>();
    return new Set(dow.split(",").map(Number));
  }, [dow]);

  const toggleDow = (d: number) => {
    const s = new Set(selectedDows);
    if (s.has(d)) s.delete(d); else s.add(d);
    const next = s.size === 0 ? "*" : Array.from(s).sort((a,b)=>a-b).join(",");
    setDow(next);
    emit(minute, hour, dom, month, next);
  };

  const emit = (m: string, h: string, d: string, mo: string, dw: string) => {
    onChange(`${m} ${h} ${d} ${mo} ${dw}`);
  };

  const handleMinute = (v: string, mode: "fixed" | "every") => {
    const expr = mode === "every" ? `*/${v}` : v;
    setMinute(expr);
    emit(expr, hour, dom, month, dow);
  };

  const handleHour = (v: string, mode: "fixed" | "every") => {
    const expr = mode === "every" ? `*/${v}` : v;
    setHour(expr);
    emit(minute, expr, dom, month, dow);
  };

  return (
    <div className="space-y-3 rounded-xl border border-[#E8E6E1] dark:border-[#2a2d3a] p-3">
      {/* Minute */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-600 dark:text-gray-400 w-16 shrink-0">Минуты</span>
          <div className="flex rounded-md border border-[#E8E6E1] dark:border-[#2a2d3a] overflow-hidden text-[11px]">
            {(["fixed","every"] as const).map(m => (
              <button key={m} onClick={() => { setMinuteMode(m); handleMinute(minuteMode === "every" ? minute.replace("*/","") : minute, m); }}
                className={cn("px-2 py-0.5 transition-colors", minuteMode === m ? "bg-indigo-600 text-white" : "text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800")}>
                {m === "fixed" ? "В минуту" : "Каждые N"}
              </button>
            ))}
          </div>
          <input
            type="number"
            min={minuteMode === "every" ? 1 : 0}
            max={minuteMode === "every" ? 59 : 59}
            className="w-16 px-2 py-1 rounded-md border border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-gray-900 text-xs text-center text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            value={minute.replace("*/", "")}
            onChange={e => handleMinute(e.target.value, minuteMode)}
          />
          <span className="text-xs text-gray-400">{minuteMode === "every" ? "мин" : ""}</span>
        </div>
      </div>

      {/* Hour */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-600 dark:text-gray-400 w-16 shrink-0">Часы</span>
          <div className="flex rounded-md border border-[#E8E6E1] dark:border-[#2a2d3a] overflow-hidden text-[11px]">
            {(["fixed","every"] as const).map(m => (
              <button key={m} onClick={() => { setHourMode(m); handleHour(hourMode === "every" ? hour.replace("*/","") : hour, m); }}
                className={cn("px-2 py-0.5 transition-colors", hourMode === m ? "bg-indigo-600 text-white" : "text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800")}>
                {m === "fixed" ? "В час" : "Каждые N"}
              </button>
            ))}
          </div>
          <input
            type="number"
            min={hourMode === "every" ? 1 : 0}
            max={hourMode === "every" ? 23 : 23}
            className="w-16 px-2 py-1 rounded-md border border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-gray-900 text-xs text-center text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            value={hour.replace("*/", "")}
            onChange={e => handleHour(e.target.value, hourMode)}
          />
          <span className="text-xs text-gray-400">{hourMode === "every" ? "ч" : ":00"}</span>
        </div>
      </div>

      {/* Day of week */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-gray-600 dark:text-gray-400 w-16 shrink-0">Дни</span>
        <div className="flex gap-1">
          {DOW_LABELS.map((d, i) => (
            <button
              key={i}
              onClick={() => toggleDow(i)}
              className={cn(
                "w-7 h-7 rounded-full text-[10px] font-medium transition-colors",
                selectedDows.has(i)
                  ? "bg-indigo-600 text-white"
                  : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
              )}
            >
              {d}
            </button>
          ))}
          <button
            onClick={() => { setDow("*"); emit(minute, hour, dom, month, "*"); }}
            className={cn(
              "px-2 h-7 rounded-full text-[10px] font-medium transition-colors",
              dow === "*"
                ? "bg-indigo-600 text-white"
                : "bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
            )}
          >
            Все
          </button>
        </div>
      </div>

      {/* Result preview */}
      <div className="flex items-center gap-2 pt-1 border-t border-[#E8E6E1] dark:border-[#2a2d3a]">
        <span className="text-[10px] text-gray-400">Результат:</span>
        <code className="text-xs font-mono bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded text-gray-700 dark:text-gray-300">
          {minute} {hour} {dom} {month} {dow}
        </code>
        <span className="text-xs text-gray-500 dark:text-gray-400">{cronToLabel(`${minute} ${hour} ${dom} ${month} ${dow}`)}</span>
      </div>
    </div>
  );
}
