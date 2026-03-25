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

// ─── Token persistence ───────────────────────────────────────────────────────

const TOKEN_KEY = "orion_session_token";

export function getStoredToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setStoredToken(token: string) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* ignore */ }
}

export function clearStoredToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

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
  const token = getStoredToken();
  const authHeaders: Record<string, string> = {};
  if (token) authHeaders["Authorization"] = `Bearer ${token}`;

  const res = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
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
  login: async (email: string, password: string) => {
    const resp = await post<LoginResponse>("/api/auth/login", { email, password });
    if (resp.token) setStoredToken(resp.token);
    return resp;
  },
  logout: async () => {
    const resp = await post<{ ok: boolean }>("/api/auth/logout");
    clearStoredToken();
    return resp;
  },
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
  create: (title?: string, model?: string, mode?: string) =>
    post<{ chat: ChatSummary }>("/api/chats", { title, model, mode }),
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
  mode?: string;
  fileContent?: string;
}

/**
 * Send a message and get back an SSE stream.
 * The caller is responsible for reading the stream.
 */
function sendMessage(opts: SendMessageOptions): Promise<Response> {
  const token = getStoredToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(`/api/chats/${opts.chatId}/send`, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify({
      message: opts.message,
      model: opts.model,
      variant: opts.variant,
      mode: opts.mode,
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
    username?: string;
    role?: string;
    budget_limit?: number;
    permissions?: Record<string, boolean>;
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

// ─── Memory ──────────────────────────────────────────────────────────────────

export interface MemoryEntry {
  id: string;
  content: string;
  source?: string;
  tags?: string[];
  created_at: string;
  relevance?: number;
}

const memory = {
  list: (chatId?: string) =>
    get<{ memories: MemoryEntry[] }>("/api/memory", chatId ? { chat_id: chatId } : undefined),
  search: (query: string, chatId?: string) =>
    post<{ memories: MemoryEntry[] }>("/api/memory/search", { query, chat_id: chatId }),
  store: (content: string, source?: string, tags?: string[]) =>
    post<{ ok: boolean; memory: MemoryEntry }>("/api/memory", { content, source, tags }),
  delete: (id: string) => del<{ ok: boolean }>(`/api/memory/${id}`),
  stats: () => get<{ total: number; sessions?: number; size_kb?: number; initialized?: boolean; vector_dim?: number; collection?: string }>("/api/memory/stats"),
  adminList: (userId?: string) =>
    get<{ memories: MemoryEntry[] }>("/api/admin/memory", userId ? { user_id: userId } : undefined),
  adminDelete: (id: string) => del<{ ok: boolean }>(`/api/admin/memory/${id}`),
  adminClearSessions: () => post<{ ok: boolean; cleared: number }>("/api/admin/memory/clear-sessions"),
};

// ─── Custom Agents ────────────────────────────────────────────────────────────

export interface CustomAgent {
  id: string;
  name: string;
  description?: string;
  system_prompt: string;
  model?: string;
  tools?: string[];
  created_at: string;
}

const agents = {
  list: () => get<{ agents: CustomAgent[] }>("/api/agents/custom"),
  create: (data: Omit<CustomAgent, "id" | "created_at">) =>
    post<{ ok: boolean; agent: CustomAgent }>("/api/agents/custom", data),
  delete: (id: string) => del<{ ok: boolean }>(`/api/agents/custom/${id}`),
};

// ─── Models ───────────────────────────────────────────────────────────────────

export interface ModelInfo {
  id: string;
  name: string;
  provider?: string;
  context_length?: number;
  cost_per_1k_input?: number;
  cost_per_1k_output?: number;
  available?: boolean;
}

const models = {
  list: async (): Promise<{ models: ModelInfo[] }> => {
    const raw = await get<{
      chat_models?: Record<string, { name: string; lang?: string }>;
      configs?: Record<string, { name: string; emoji?: string; quality?: number; monthly_cost?: string; coding_model?: string }>;
      models?: ModelInfo[];
    }>("/api/models");
    // If already in expected format
    if (raw.models) return { models: raw.models };
    // Transform from backend format
    const result: ModelInfo[] = [];
    if (raw.configs) {
      Object.entries(raw.configs).forEach(([id, cfg]) => {
        result.push({
          id,
          name: cfg.name,
          provider: "orion",
          available: true,
        });
      });
    }
    if (raw.chat_models) {
      Object.entries(raw.chat_models).forEach(([id, m]) => {
        if (!result.find(r => r.id === id)) {
          result.push({ id, name: m.name, provider: "orion", available: true });
        }
      });
    }
    return { models: result };
  },
};

// ─── Templates ────────────────────────────────────────────────────────────────

export interface TaskTemplate {
  id: string;
  title?: string;
  name?: string;
  description?: string;
  prompt: string;
  category?: string;
  tags?: string[];
}

const templates = {
  list: () => get<{ templates: TaskTemplate[] }>("/api/templates"),
};

// ─── Connectors ───────────────────────────────────────────────────────────────

export interface Connector {
  id: string;
  name: string;
  type?: string;
  description?: string;
  connected?: boolean;
  status?: string;
  auth_type?: string;
  scopes?: string[];
  icon?: string;
  config?: Record<string, unknown>;
}

const connectors = {
  list: () => get<{ connectors: Connector[] }>("/api/connectors"),
  connect: (id: string, config?: Record<string, unknown>) =>
    post<{ ok: boolean }>(`/api/connectors/${id}/connect`, config || {}),
  disconnect: (id: string) => post<{ ok: boolean }>(`/api/connectors/${id}/disconnect`),
};

// ─── Rate Limit ───────────────────────────────────────────────────────────────

export interface RateLimitStatus {
  requests_per_minute: number;
  requests_used: number;
  tokens_per_minute: number;
  tokens_used: number;
  reset_at: string;
}

const rateLimit = {
  status: () => get<RateLimitStatus>("/api/rate-limit/status"),
};

// ─── Files ────────────────────────────────────────────────────────────────────

export interface FileEntry {
  id: string;
  name: string;
  size: number;
  mime_type?: string;
  created_at: string;
  url?: string;
}

const files = {
  list: (chatId?: string) =>
    get<{ files: FileEntry[] }>("/api/files", chatId ? { chat_id: chatId } : undefined),
  upload: (formData: FormData) =>
    fetch("/api/upload", { method: "POST", credentials: "include", body: formData }).then(r => r.json()),
  downloadUrl: (id: string) => `/api/files/${id}/download`,
  preview: (id: string) => get<{ content: string; mime_type: string }>(`/api/files/${id}/preview`),
};

// ─── Health ───────────────────────────────────────────────────────────────────

const health = {
  check: () => get<{ status: string; version?: string; uptime?: number }>("/api/health"),
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
  memory,
  agents,
  models,
  templates,
  connectors,
  rateLimit,
  files,
  health,
};

export default api;
