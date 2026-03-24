/**
 * ORION API Client
 * ================
 * Centralised fetch wrapper for all backend endpoints.
 * Handles auth cookies, error normalisation, and JSON parsing.
 *
 * Usage:
 *   import { api } from "@/lib/api";
 *   const chats = await api.chats.list();
 */

// ─── Base fetch ───────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      message = body.error || body.message || message;
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, message);
  }

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = params
    ? `${path}?${new URLSearchParams(params).toString()}`
    : path;
  return request<T>(url, { method: "GET" });
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "manager" | "user";
  monthly_limit: number;
  total_spent: number;
  is_active: boolean;
}

export interface LoginResponse {
  ok: boolean;
  token?: string;
  user: User;
}

const auth = {
  me: () => get<{ user: User }>("/api/auth/me"),
  login: (email: string, password: string) =>
    post<LoginResponse>("/api/auth/login", { email, password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout"),
};

// ─── Chats ────────────────────────────────────────────────────────────────────

export interface ChatSummary {
  id: string;
  title: string;
  model: string;
  variant: string;
  total_cost: number;
  created_at: string;
  updated_at: string;
  pinned: boolean;
  archived: boolean;
  status?: string;
  last_message?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  timestamp: string;
  steps?: unknown[];
  plan?: string[];
}

export interface ChatDetail extends ChatSummary {
  messages: ChatMessage[];
}

const chats = {
  list: () => get<{ chats: ChatSummary[] }>("/api/chats"),
  get: (chatId: string) => get<{ chat: ChatDetail }>(`/api/chats/${chatId}`),
  create: (title?: string, model?: string) =>
    post<{ chat: ChatSummary }>("/api/chats", { title, model }),
  delete: (chatId: string) => del<{ ok: boolean }>(`/api/chats/${chatId}`),
  rename: (chatId: string, title: string) =>
    put<{ ok: boolean }>(`/api/chats/${chatId}/rename`, { title }),
  stop: (chatId: string) =>
    post<{ ok: boolean }>(`/api/chats/${chatId}/stop`),
  status: (chatId: string) =>
    get<{ status: string; running: boolean }>(`/api/chats/${chatId}/status`),
};

// ─── Agent / Send message ─────────────────────────────────────────────────────

export interface SendMessageOptions {
  chatId: string;
  message: string;
  model?: string;
  variant?: string;
  fileContent?: string;
}

/**
 * Send a message and get back an SSE stream.
 * The caller is responsible for reading the stream.
 */
function sendMessage(opts: SendMessageOptions): Promise<Response> {
  return fetch(`/api/chats/${opts.chatId}/send`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: opts.message,
      model: opts.model,
      variant: opts.variant,
      file_content: opts.fileContent,
    }),
  });
}

/**
 * Subscribe to an existing running task (SSE reconnect).
 */
function subscribeToChat(chatId: string): EventSource {
  return new EventSource(`/api/chats/${chatId}/subscribe`, {
    withCredentials: true,
  });
}

const agent = {
  send: sendMessage,
  subscribe: subscribeToChat,
};

// ─── Schedule ─────────────────────────────────────────────────────────────────

export interface ScheduleTaskSummary {
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
}

export interface ScheduleTaskDetail extends ScheduleTaskSummary {
  prompt: string;
  run_history: Array<{
    id: string;
    started_at: string;
    status: "success" | "failed" | "running";
    cost: number;
    chat_id: string | null;
    duration_s: number | null;
  }>;
}

export interface CreateScheduleTask {
  title: string;
  prompt: string;
  cron: string;
  category?: string;
}

const schedule = {
  list: () => get<{ tasks: ScheduleTaskSummary[] }>("/api/schedule"),
  get: (id: string) => get<{ task: ScheduleTaskDetail }>(`/api/schedule/${id}`),
  create: (data: CreateScheduleTask) =>
    post<{ ok: boolean; task: ScheduleTaskSummary }>("/api/schedule", data),
  update: (id: string, data: Partial<CreateScheduleTask & { status: string }>) =>
    put<{ ok: boolean; task: ScheduleTaskSummary }>(`/api/schedule/${id}`, data),
  delete: (id: string) => del<{ ok: boolean }>(`/api/schedule/${id}`),
  toggle: (id: string) =>
    post<{ ok: boolean; status: string }>(`/api/schedule/${id}/toggle`),
  runNow: (id: string) =>
    post<{ ok: boolean; run_id: string; task: ScheduleTaskSummary }>(
      `/api/schedule/${id}/run`
    ),
};

// ─── Admin ────────────────────────────────────────────────────────────────────

export interface AdminStats {
  total_users: number;
  active_tasks: number;
  success_rate: number;
  fail_rate: number;
  total_cost: number;
  avg_task_time: string;
  verifier_rejects: number;
  judge_rejects: number;
}

export interface AdminUser extends User {
  tasks: number;
  cost: number;
  lastActive: string;
}

const admin = {
  stats: () => get<AdminStats>("/api/admin/stats"),
  users: () => get<{ users: AdminUser[] }>("/api/admin/users"),
  createUser: (data: {
    email: string;
    password: string;
    name?: string;
    role?: string;
  }) => post<{ ok: boolean; user: AdminUser }>("/api/admin/users", data),
  updateUser: (id: string, data: Partial<AdminUser>) =>
    put<{ ok: boolean }>(`/api/admin/users/${id}`, data),
  deleteUser: (id: string) => del<{ ok: boolean }>(`/api/admin/users/${id}`),
  toggleUser: (id: string) =>
    post<{ ok: boolean }>(`/api/admin/users/${id}/toggle`),
  allChats: () => get<{ chats: ChatSummary[] }>("/api/admin/chats"),
  scheduleAll: () => get<{ tasks: ScheduleTaskDetail[]; total: number }>("/api/admin/schedule"),
};

// ─── Settings ─────────────────────────────────────────────────────────────────

export interface UserSettings {
  theme?: "light" | "dark" | "system";
  language?: string;
  notifications?: boolean;
  default_model?: string;
}

const settings = {
  get: () => get<{ settings: UserSettings }>("/api/settings"),
  update: (data: Partial<UserSettings>) =>
    put<{ ok: boolean; settings: UserSettings }>("/api/settings", data),
};

// ─── Analytics ────────────────────────────────────────────────────────────────

const analytics = {
  get: (period?: string) =>
    get<Record<string, unknown>>("/api/analytics", period ? { period } : undefined),
};

// ─── Export ───────────────────────────────────────────────────────────────────

export const api = {
  auth,
  chats,
  agent,
  schedule,
  admin,
  settings,
  analytics,
};

export default api;
