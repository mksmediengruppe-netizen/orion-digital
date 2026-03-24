// ORION Schedule API hook
// Connects to the real backend /api/schedule endpoints.
// Falls back to mock data when backend is unavailable (prototype mode).

import { useState, useEffect, useCallback } from "react";
import type {
  ScheduledTask,
  RunHistoryEntry,
  RunResult,
} from "@/components/orion/ScheduledTasksPanel";

// ─── API helpers ──────────────────────────────────────────────────────────────

const API_BASE = "/api";

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface ApiTask {
  id: string;
  title: string;
  category: string;
  cron: string;
  status: "active" | "paused" | "running" | "failed";
  total_runs: number;
  total_cost: number;
  avg_cost: number;
  last_run_at: string | null;
  last_run_status: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
  prompt?: string;
  run_history?: ApiRunRecord[];
}

interface ApiRunRecord {
  id: string;
  started_at: string;
  status: "success" | "failed" | "running";
  cost: number;
  chat_id: string | null;
  duration_s: number | null;
}

export interface CreateTaskData {
  title: string;
  prompt: string;
  cron: string;
  category?: string;
}

// ─── Converters ───────────────────────────────────────────────────────────────

function formatRelativeTime(isoStr: string | null): string {
  if (!isoStr) return "никогда";
  const date = new Date(isoStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffMin < 2) return "только что";
  if (diffMin < 60) return `${diffMin} мин назад`;
  if (diffHour < 24) return `${diffHour} ч назад`;
  if (diffDay === 1) return "вчера";
  return `${diffDay} дней назад`;
}

function formatCost(cost: number): string {
  return `$${cost.toFixed(2)}`;
}

// Simulate next N run times for a cron expression (client-side)
function getNextRuns(expr: string, count = 5): string[] {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return [];
  const [minStr, hourStr, domStr, , dowStr] = parts;

  const now = new Date();
  const results: string[] = [];
  const pad = (n: number) => String(n).padStart(2, "0");
  const fmt = (d: Date) => {
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    if (d.toDateString() === today.toDateString())
      return `сегодня в ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (d.toDateString() === tomorrow.toDateString())
      return `завтра в ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const days = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
    return `${days[d.getDay()]} ${pad(d.getDate())}.${pad(d.getMonth() + 1)} в ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const minute = minStr === "*" ? -1 : minStr.startsWith("*/") ? -2 : parseInt(minStr);
  const hour = hourStr === "*" ? -1 : hourStr.startsWith("*/") ? -2 : parseInt(hourStr);
  const stepM = minStr.startsWith("*/") ? parseInt(minStr.slice(2)) : 0;
  const stepH = hourStr.startsWith("*/") ? parseInt(hourStr.slice(2)) : 0;

  const cursor = new Date(now);
  cursor.setSeconds(0, 0);
  cursor.setMinutes(cursor.getMinutes() + 1);

  for (let i = 0; i < 500 && results.length < count; i++) {
    const m = cursor.getMinutes();
    const h = cursor.getHours();
    const dom = cursor.getDate();
    const dow = cursor.getDay();
    const mo = cursor.getMonth() + 1;

    const minuteOk = minute === -1 ? true : minute === -2 ? m % stepM === 0 : m === minute;
    const hourOk = hour === -1 ? true : hour === -2 ? h % stepH === 0 : h === hour;
    const domOk = domStr === "*" ? true : parseInt(domStr) === dom;
    const monthOk = true; // simplified
    const dowOk = dowStr === "*" ? true : dowStr.split(",").map(Number).includes(dow);

    if (minuteOk && hourOk && domOk && monthOk && dowOk) {
      results.push(fmt(new Date(cursor)));
    }
    cursor.setMinutes(cursor.getMinutes() + 1);
  }
  return results;
}

function cronToLabel(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, dom, , dow] = parts;

  if (expr === "* * * * *") return "Каждую минуту";
  if (expr === "0 * * * *") return "Каждый час";
  if (min !== "*" && hour !== "*" && dom === "*" && dow === "*")
    return `Ежедневно в ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
  if (min !== "*" && hour !== "*" && dom === "*" && dow !== "*") {
    const days = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
    const d = dow.split(",").map((n) => days[parseInt(n)] ?? n).join(", ");
    return `По ${d} в ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
  }
  if (min !== "*" && hour !== "*" && dom !== "*" && dow === "*")
    return `${dom}-го числа в ${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;
  if (min.startsWith("*/")) return `Каждые ${min.slice(2)} мин`;
  if (hour.startsWith("*/")) return `Каждые ${hour.slice(2)} ч`;
  return `По расписанию (${expr})`;
}

function apiTaskToScheduled(t: ApiTask): ScheduledTask {
  const history: RunHistoryEntry[] = (t.run_history || []).map((r) => ({
    id: r.id,
    startedAt: formatRelativeTime(r.started_at),
    duration: r.duration_s ? `${r.duration_s}с` : "...",
    status: r.status as RunResult,
    cost: formatCost(r.cost),
  }));

  return {
    id: t.id,
    title: t.title,
    category: t.category || "Общее",
    description: t.prompt || "",
    prompt: t.prompt || "",
    cron: t.cron,
    cronLabel: cronToLabel(t.cron),
    nextRuns: getNextRuns(t.cron),
    lastRun: formatRelativeTime(t.last_run_at),
    lastStatus: (t.last_run_status as RunResult) || null,
    status: t.status,
    runCount: t.total_runs,
    avgCost: formatCost(t.avg_cost),
    history,
    createdAt: t.created_at
      ? new Date(t.created_at).toLocaleDateString("ru-RU", {
          day: "numeric",
          month: "short",
          year: "numeric",
        })
      : "",
  };
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export interface UseScheduleAPIResult {
  tasks: ScheduledTask[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
  createTask: (data: CreateTaskData) => Promise<ScheduledTask>;
  updateTask: (id: string, data: Partial<ApiTask>) => Promise<ScheduledTask>;
  deleteTask: (id: string) => Promise<void>;
  toggleTask: (id: string) => Promise<void>;
  runNow: (id: string) => Promise<void>;
  getTaskDetail: (id: string) => Promise<ScheduledTask>;
}

export function useScheduleAPI(): UseScheduleAPIResult {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ tasks: ApiTask[] }>("/schedule");
      setTasks(data.tasks.map(apiTaskToScheduled));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  const createTask = useCallback(async (data: CreateTaskData) => {
    const res = await apiFetch<{ task: ApiTask }>("/schedule", {
      method: "POST",
      body: JSON.stringify(data),
    });
    const newTask = apiTaskToScheduled(res.task);
    setTasks((prev) => [newTask, ...prev]);
    return newTask;
  }, []);

  const updateTask = useCallback(async (id: string, data: Partial<ApiTask>) => {
    const res = await apiFetch<{ task: ApiTask }>(`/schedule/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
    const updated = apiTaskToScheduled(res.task);
    setTasks((prev) => prev.map((t) => (t.id === id ? updated : t)));
    return updated;
  }, []);

  const deleteTask = useCallback(async (id: string) => {
    await apiFetch(`/schedule/${id}`, { method: "DELETE" });
    setTasks((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toggleTask = useCallback(async (id: string) => {
    const res = await apiFetch<{ status: string }>(`/schedule/${id}/toggle`, {
      method: "POST",
    });
    setTasks((prev) =>
      prev.map((t) =>
        t.id === id
          ? { ...t, status: res.status as ScheduledTask["status"] }
          : t
      )
    );
  }, []);

  const runNow = useCallback(async (id: string) => {
    const res = await apiFetch<{ task: ApiTask }>(`/schedule/${id}/run`, {
      method: "POST",
    });
    const updated = apiTaskToScheduled(res.task);
    setTasks((prev) => prev.map((t) => (t.id === id ? updated : t)));
  }, []);

  const getTaskDetail = useCallback(async (id: string) => {
    const res = await apiFetch<{ task: ApiTask }>(`/schedule/${id}`);
    return apiTaskToScheduled(res.task);
  }, []);

  return {
    tasks,
    loading,
    error,
    refresh: fetchTasks,
    createTask,
    updateTask,
    deleteTask,
    toggleTask,
    runNow,
    getTaskDetail,
  };
}
