/**
 * ARCANE 2 — API Client v3
 * ========================
 * Written against EXACT response formats from api/api.py (clean backend).
 * 
 * EXISTING ENDPOINTS (api.py, 15 total):
 *   GET  /api/health
 *   GET  /api/models
 *   POST /api/projects
 *   GET  /api/projects
 *   GET  /api/projects/{id}
 *   POST /api/projects/{id}/tasks
 *   GET  /api/runs/{run_id}
 *   POST /api/runs/{run_id}/cancel
 *   GET  /api/budget
 *   GET  /api/budget/{project_id}
 *   POST /api/dog-racing
 *   GET  /api/leaderboard
 *   POST /api/consolidation
 *   POST /api/collective-mind
 *   WS   /ws/{project_id}
 *
 * COMPAT LAYER ENDPOINTS (compat_all.py, added via include_router):
 *   POST /api/auth/login
 *   POST /api/auth/logout
 *   GET  /api/auth/me
 *   CRUD /api/chats/*
 *   CRUD /api/schedule/*
 *   CRUD /api/admin/*
 */

// Use Vite proxy in dev (empty base), or explicit URL if VITE_API_URL is set
const API_BASE = import.meta.env.VITE_API_URL || '';

// ═══════════════════════════════════════════════════════════════════════════════
// TYPES — exact match to backend response shapes
// ═══════════════════════════════════════════════════════════════════════════════

// ── From api.py GET /api/models ──────────────────────────────────────────────

export interface BackendLLMModel {
  id: string;
  name: string;                  // display_name from ModelSpec
  input_price: number;           // $/M tokens
  output_price: number;
  max_context: number;           // raw tokens (e.g. 200000)
  tool_calling: string;          // "reliable" | "basic" | "none"
  categories: string[];          // ["reasoning", "code"] etc
  is_free: boolean;
  swe_bench: number | null;
}

export interface BackendImageModel {
  id: string;
  name: string;
  price_per_image: number;
  best_for: string;
  is_free: boolean;
}

// ── From api.py project endpoints ────────────────────────────────────────────

export interface BackendProject {
  id: string;
  name: string;
  description: string;
  client: string;
  mode: string;
  budget_limit: number;
  status: string;
  created_at: number;            // unix timestamp
}

// ── From api.py POST /api/projects/{id}/tasks ────────────────────────────────

export interface BackendRunResult {
  run_id: string;
  project_id: string;
  task: string;
  status: string;                // queued|classifying|running|done|failed|cancelled
  task_type: string;
  complexity: string;
  mode: string;
  team: Record<string, string>;  // role → model_id
  estimated_cost: number;
  output: string;
  artifacts: string[];
  actual_cost: number;
  cost_breakdown: Array<Record<string, unknown>>;
  started_at: number;
  finished_at: number;
  duration_seconds: number;
  errors: string[];
  retries: number;
  escalations: string[];
}

// ── From api.py POST /api/dog-racing ─────────────────────────────────────────

export interface BackendRaceResult {
  model_id: string;
  status: string;
  output: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  time_seconds: number;
}

// ── From api.py POST /api/consolidation ──────────────────────────────────────

export interface BackendConsolidationResult {
  status: string;
  consensus: string;
  unique_insights: string[];
  contradictions: string[];
  recommendation: string;
  responses: unknown[];
  consolidator_model: string;
  total_cost_usd: number;
  total_latency_s: number;
}

// ── From api.py POST /api/collective-mind ─────────────────────────────────────

export interface BackendCollectiveMindResult {
  status: string;
  final_answer: string;
  consensus: string;
  disagreements: string[];
  contributions: Record<string, unknown>;
  confidence: number;
  models_used: string[];
  judge_model: string;
  num_rounds: number;
  total_cost_usd: number;
  total_latency_s: number;
}

// ── Compat layer types (from compat_all.py) ──────────────────────────────────

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  status: string;
  created_at: string;
}

export interface CompatChat {
  id: string;
  title: string;
  model: string;
  mode: string;
  user_id: string;
  project_id?: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message: string | null;
  status: string;
  total_cost: number;
}

export interface CompatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  model?: string;
  cost_usd?: number;
}

export interface CompatScheduleTask {
  id: string;
  name: string;
  cron: string;
  task: string;
  model: string | null;
  project_id: string | null;
  enabled: boolean;
  created_at: string;
  last_run: string | null;
  next_run: string | null;
  run_count: number;
}

export interface CompatGroup {
  id: string;
  name: string;
  description: string;
  managerId: string | null;
  memberIds: string[];
  budget: Record<string, unknown> | null;
  spent: number;
  color: string;
}

// ═══════════════════════════════════════════════════════════════════════════════
// TOKEN STORAGE
// ═══════════════════════════════════════════════════════════════════════════════

const TOKEN_KEY = 'arcane_token';

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string) {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* */ }
}
export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* */ }
}

// ═══════════════════════════════════════════════════════════════════════════════
// BASE FETCH
// ═══════════════════════════════════════════════════════════════════════════════

export class ApiError extends Error {
  constructor(public status: number, msg: string) { super(msg); this.name = 'ApiError'; }
}

// Sanitize error messages to avoid leaking internal details or model names
export function sanitizeErrorMessage(msg: string): string {
  if (!msg) return 'Ошибка выполнения';
  // Strip model provider names
  const sanitized = msg
    .replace(/openai|anthropic|google|mistral|cohere|openrouter/gi, 'AI')
    .replace(/gpt-[\w.-]+/gi, 'AI model')
    .replace(/claude-[\w.-]+/gi, 'AI model')
    .replace(/gemini-[\w.-]+/gi, 'AI model')
    .replace(/sk-or-v1-[\w]+/gi, '[key]')
    .replace(/sk-[\w]{20,}/gi, '[key]')
    .replace(/Bearer [\w.-]+/gi, 'Bearer [token]')
    .replace(/\/root\/arcane2[^\s]*/gi, '[path]')
    .replace(/\/home\/[^\s]*/gi, '[path]');
  return sanitized;
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include', headers, ...opts });

  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent('arcane:unauthorized'));
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const b = await res.json(); msg = b.detail || b.error || b.message || msg; } catch { /* */ }
    throw new ApiError(res.status, sanitizeErrorMessage(msg));
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

const GET  = <T>(p: string, params?: Record<string, string>) => req<T>(params ? `${p}?${new URLSearchParams(params)}` : p);
const POST = <T>(p: string, body?: unknown) => req<T>(p, { method: 'POST', body: body != null ? JSON.stringify(body) : undefined });
const PUT  = <T>(p: string, body?: unknown) => req<T>(p, { method: 'PUT', body: body != null ? JSON.stringify(body) : undefined });
const DEL  = <T>(p: string) => req<T>(p, { method: 'DELETE' });

// ═══════════════════════════════════════════════════════════════════════════════
// API — CORE (endpoints that EXIST in clean api.py)
// ═══════════════════════════════════════════════════════════════════════════════

export const api = {

  health: () => GET<{ status: string; version: string; orchestrator: boolean; timestamp: number }>('/api/health'),

  // ── Models ─────────────────────────────────────────────────────────────
  // Response: { llm_models, image_models, manus, total_llm, total_image, total_free }
  models: {
    list: () => GET<{
      llm_models: BackendLLMModel[];
      image_models: BackendImageModel[];
      manus: { monthly_cost: number; monthly_credits: number; credit_price: number };
      total_llm: number;
      total_image: number;
      total_free: number;
    }>('/api/models'),
  },

  // ── Projects ───────────────────────────────────────────────────────────
  // create → { project, path }
  // list   → { projects: [...], total }
  // get    → { project: {...} }
  projects: {
    create: (data: { name: string; description?: string; client?: string; mode?: string; budget_limit?: number }) =>
      POST<{ project: BackendProject; path: string }>('/api/projects', data),

    list: () => GET<{ projects: BackendProject[]; total: number }>('/api/projects'),

    get: (id: string) => GET<{ project: BackendProject }>(`/api/projects/${id}`),
  },

  // ── Tasks / Runs ───────────────────────────────────────────────────────
  // submit → { run: RunResult }
  // getRun → { run: RunResult }
  // cancel → { cancelled, run_id }
  // list   → { tasks: [...] }  (from compat layer)
  tasks: {
    list: (projectId: string) => GET<{ tasks: Array<{
      id: string; run_id: string; name: string; status: string;
      cost: number; duration: string; model: string; createdAt: number;
      output: string; artifacts: string[];
    }> }>(`/api/projects/${projectId}/tasks`),

    submit: (projectId: string, data: {
      task: string; mode?: string; budget_limit?: number;
      auto_approve?: boolean; consolidation?: boolean;
      consolidation_models?: string[];
    }) => POST<{ run: BackendRunResult }>(`/api/projects/${projectId}/tasks`, data),

    getRun: (runId: string) => GET<{ run: BackendRunResult }>(`/api/runs/${runId}`),

    cancel: (runId: string) => POST<{ cancelled: boolean; run_id: string }>(`/api/runs/${runId}/cancel`),
  },

  // ── Budget ─────────────────────────────────────────────────────────────
  // global  → { total_spent_usd, total_manus_credits, by_project, by_model }
  // project → { project_id, spent_usd, manus_credits, breakdown }
  budget: {
    global: () => GET<{
      total_spent_usd: number; total_manus_credits: number;
      by_project: Record<string, number>; by_model: Record<string, number>;
    }>('/api/budget'),

    project: (id: string) => GET<{
      project_id: string; spent_usd: number; manus_credits: number;
      breakdown: Array<Record<string, unknown>>;
    }>(`/api/budget/${id}`),
  },

  // ── Dog Racing ─────────────────────────────────────────────────────────
  // start → { race_id, task, category, results: [...], status, total_cost_usd }
  dogRacing: {
    start: (data: { task: string; models: string[]; category?: string; project_id?: string }) =>
      POST<{
        race_id: string; task: string; category: string;
        results: BackendRaceResult[]; status: string; total_cost_usd: number;
      }>('/api/dog-racing', data),

    leaderboard: (category?: string) =>
      GET<{ leaderboard: unknown[]; category: string; total_races: number }>(
        '/api/leaderboard', category ? { category } : undefined),
  },

  // ── Consolidation ──────────────────────────────────────────────────────
  consolidation: {
    run: (data: { task: string; models: string[]; consolidator?: string; project_id?: string }) =>
      POST<BackendConsolidationResult>('/api/consolidation', data),
  },

  // ── Collective Mind ────────────────────────────────────────────────────
  // NOTE: field is "prompt" not "task" in the backend CollectiveMindRequest
  collectiveMind: {
    run: (data: { prompt: string; models: string[]; rounds?: number; judge?: string; project_id?: string }) =>
      POST<BackendCollectiveMindResult>('/api/collective-mind', data),
  },

  // ── Project Files ────────────────────────────────────────────────────────
  files: {
    list: (projectId: string) => GET<{
      files: Array<{
        name: string; path: string; size: number;
        mime: string; modified: number;
      }>;
      project_id: string;
    }>(`/api/projects/${projectId}/files`),

    downloadUrl: (projectId: string, filePath: string) =>
      `/api/projects/${projectId}/files/${filePath}`,

    archiveUrl: (projectId: string) =>
      `/api/projects/${projectId}/files/archive`,
  },

  // ── WebSocket URL ──────────────────────────────────────────────────────
  wsUrl: (projectId: string) => {
    // Use relative WebSocket URL so Vite proxy handles it (ws:// upgrade)
    const origin = window.location.origin;
    return origin.replace(/^http/, 'ws') + `/ws/${projectId}`;
  },

  // ═════════════════════════════════════════════════════════════════════════
  // COMPAT LAYER (endpoints from compat_all.py — require include_router)
  // These DO NOT exist in clean api.py. They are added by the compat layer.
  // ═════════════════════════════════════════════════════════════════════════

  auth: {
    login: (creds: { login_id: string; password: string }) =>
      POST<{ ok: boolean; token: string; user: AuthUser }>('/api/auth/login', creds),
    logout: () => POST<{ ok: boolean }>('/api/auth/logout'),
    me: () => GET<{ user: AuthUser }>('/api/auth/me'),
  },

  chats: {
    list: () => GET<{ chats: CompatChat[] }>('/api/chats'),
    get: (id: string) => GET<{ chat: CompatChat & { messages: CompatMessage[] } }>(`/api/chats/${id}`),
    create: (data: { title: string; model?: string; mode?: string; project_id?: string }) =>
      POST<{ chat: CompatChat }>('/api/chats', data),
    delete: (id: string) => DEL<{ ok: boolean }>(`/api/chats/${id}`),
    rename: (id: string, title: string) => PUT<{ ok: boolean }>(`/api/chats/${id}/rename`, { title }),
    send: (id: string, data: { content: string; model?: string; mode?: string }) =>
      POST<{ ok: boolean; message: CompatMessage; total_cost: number }>(`/api/chats/${id}/send`, data),
    stop: (id: string) => POST<{ ok: boolean }>(`/api/chats/${id}/stop`),
    status: (id: string) => GET<{ chat_id: string; status: string; total_cost: number }>(`/api/chats/${id}/status`),
    setModel: (id: string, model: string) => POST<{ ok: boolean }>(`/api/chats/${id}/model`, { model }),
    /** SSE subscribe URL — pass to new EventSource() */
    subscribeUrl: (id: string) => `${API_BASE}/api/chats/${id}/subscribe`,
  },

  schedule: {
    list: () => GET<{ tasks: CompatScheduleTask[] }>('/api/schedule'),
    create: (data: { name: string; cron: string; task: string; model?: string; project_id?: string; enabled?: boolean }) =>
      POST<{ ok: boolean; task: CompatScheduleTask }>('/api/schedule', data),
    get: (id: string) => GET<{ task: CompatScheduleTask }>(`/api/schedule/${id}`),
    update: (id: string, data: Partial<CompatScheduleTask>) => PUT<{ ok: boolean; task: CompatScheduleTask }>(`/api/schedule/${id}`, data),
    delete: (id: string) => DEL<{ ok: boolean }>(`/api/schedule/${id}`),
    toggle: (id: string) => POST<{ ok: boolean; status: string }>(`/api/schedule/${id}/toggle`),
    runNow: (id: string) => POST<{ ok: boolean; status: string }>(`/api/schedule/${id}/run`),
  },

  admin: {
    stats: () => GET<{ total_users: number; total_chats: number; total_messages: number; total_cost_usd: number }>('/api/admin/stats'),
    users: {
      list: () => GET<{ users: AuthUser[] }>('/api/admin/users'),
      create: (data: { email: string; name: string; password: string; role?: string }) =>
        POST<{ ok: boolean; user: AuthUser }>('/api/admin/users', data),
      update: (id: string, data: Partial<AuthUser>) => PUT<{ ok: boolean }>(`/api/admin/users/${id}`, data),
      delete: (id: string) => DEL<{ ok: boolean }>(`/api/admin/users/${id}`),
      toggle: (id: string) => POST<{ ok: boolean }>(`/api/admin/users/${id}/toggle`),
    },
    groups: {
      list: () => GET<{ groups: CompatGroup[] }>('/api/admin/groups'),
      create: (data: { name: string; description?: string; color?: string }) =>
        POST<{ ok: boolean; group: CompatGroup }>('/api/admin/groups', data),
      update: (id: string, data: Partial<CompatGroup>) => PUT<{ ok: boolean }>(`/api/admin/groups/${id}`, data),
      delete: (id: string) => DEL<{ ok: boolean }>(`/api/admin/groups/${id}`),
      addMember: (gid: string, uid: string) => POST<{ ok: boolean }>(`/api/admin/groups/${gid}/members`, { user_id: uid }),
      removeMember: (gid: string, uid: string) => DEL<{ ok: boolean }>(`/api/admin/groups/${gid}/members/${uid}`),
    },
    logs: {
      list: (params?: { limit?: string; offset?: string; userId?: string }) =>
        GET<{ logs: unknown[]; total: number }>('/api/admin/logs', params),
    },
    spending: {
      overview: () => GET<{ total: number; by_user: unknown[]; by_model: unknown[]; by_project: unknown[]; daily: unknown[] }>('/api/admin/spending'),
    },
    budgets: {
      getOrg: () => GET<{ budget: Record<string, unknown> }>('/api/admin/budgets/org'),
      setOrg: (budget: Record<string, unknown>) => PUT<{ ok: boolean }>('/api/admin/budgets/org', budget),
      getUser: (uid: string) => GET<{ budget: unknown; spent: number }>(`/api/admin/budgets/users/${uid}`),
      setUser: (uid: string, budget: unknown) => PUT<{ ok: boolean }>(`/api/admin/budgets/users/${uid}`, { budget }),
    },
    settings: {
      getKeys: () => GET<{ openrouter: { set: boolean; masked: string }; manus: { set: boolean; masked: string }; tavily: { set: boolean; masked: string } }>('/api/admin/settings/keys'),
      setKey: (provider: string, key: string) => POST<{ ok: boolean }>('/api/admin/settings/keys', { provider, key }),
      testKey: (provider: string) => POST<{ ok: boolean; valid: boolean; error?: string }>('/api/admin/settings/keys/test', { provider }),
    },
    chats: () => GET<{ chats: CompatChat[] }>('/api/admin/chats'),
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

export function formatCost(cost: number): string {
  if (cost === 0) return '$0.00';
  if (cost < 0.001) return `$${(cost * 1_000_000).toFixed(0)}µ`;
  if (cost < 0.01) return `$${(cost * 1000).toFixed(2)}m`;
  return `$${cost.toFixed(4)}`;
}

export function formatCostShort(cost: number): string {
  if (cost === 0) return '$0';
  if (cost < 0.01) return '<$0.01';
  return `$${cost.toFixed(2)}`;
}

export default api;
