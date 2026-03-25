// ORION CurrentUserContext — Real API Integration
// Provides the currently logged-in user's profile from the real backend.

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import api from "@/lib/api";
import { clearStoredToken } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

export type UserRole = "admin" | "manager" | "user" | "viewer";

export interface AllowedTool {
  id: string;
  label: string;
  icon: string;
  enabled: boolean;
  description: string;
}

export interface CurrentUser {
  id: string;
  name: string;
  email: string;
  avatar?: string;
  role: UserRole;
  budgetLimit: number;   // USD
  budgetSpent: number;   // USD
  allowedTools: AllowedTool[];
  joinedAt: string;
  lastActive: string;
  settings?: Record<string, unknown>;
}

// ─── Default tools for all users ─────────────────────────────────────────────

const DEFAULT_TOOLS: AllowedTool[] = [
  { id: "browser",  label: "Браузер",      icon: "🌐", enabled: true,  description: "Управление браузером, веб-поиск" },
  { id: "terminal", label: "Терминал",     icon: "⌨️", enabled: true,  description: "Выполнение shell-команд" },
  { id: "ssh",      label: "SSH",          icon: "🔐", enabled: true,  description: "Подключение к удалённым серверам" },
  { id: "files",    label: "Файлы",        icon: "📁", enabled: true,  description: "Чтение и запись файлов" },
  { id: "images",   label: "Изображения",  icon: "🖼️", enabled: true,  description: "Генерация и обработка изображений" },
  { id: "api",      label: "API-вызовы",   icon: "🔌", enabled: true,  description: "Запросы к внешним API" },
];

// ─── Context ──────────────────────────────────────────────────────────────────

interface CurrentUserContextValue {
  currentUser: CurrentUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  // kept for backward compat with components that use setRole
  setRole: (role: UserRole) => void;
  setBudgetSpent: (amount: number) => void;
  isAdmin: boolean;
  isManager: boolean;
  canRunTasks: boolean;
  canViewOnly: boolean;
  budgetExhausted: boolean;
  budgetPct: number;
}

const CurrentUserContext = createContext<CurrentUserContextValue | null>(null);

// ─── Helper: map API response to CurrentUser ──────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mapApiUser(apiUser: any): CurrentUser {
  return {
    id: apiUser.id,
    name: apiUser.full_name || apiUser.name || apiUser.email,
    email: apiUser.email,
    role: (apiUser.role as UserRole) || "user",
    budgetLimit: apiUser.monthly_limit ?? 999999,
    budgetSpent: apiUser.total_spent ?? 0,
    allowedTools: DEFAULT_TOOLS,
    joinedAt: "",
    lastActive: "сейчас",
    settings: apiUser.settings,
  };
}

// ─── Provider ─────────────────────────────────────────────────────────────────

export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api.auth.me();
      // api.auth.me() returns { user: {...} }, extract the user object
      const userObj = (data as any).user || data;
      setCurrentUser(mapApiUser(userObj));
    } catch {
      setCurrentUser(null);
    }
  }, []);

  // On mount — check session via cookie
  useEffect(() => {
    setIsLoading(true);
    refresh().finally(() => setIsLoading(false));
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const data: any = await api.auth.login(email, password);
    if (data.user) {
      setCurrentUser(mapApiUser(data.user));
    } else {
      throw new Error("Неверный ответ сервера");
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } catch {
      // ignore
    }
    clearStoredToken();
    setCurrentUser(null);
  }, []);

  // backward compat — not used in real mode
  const setRole = useCallback((_role: UserRole) => {
    // no-op in real mode
  }, []);

  const setBudgetSpent = useCallback((amount: number) => {
    setCurrentUser((u) => (u ? { ...u, budgetSpent: amount } : u));
  }, []);

  const isAuthenticated = currentUser !== null;
  const isAdmin = currentUser?.role === "admin";
  const isManager = currentUser?.role === "manager";
  const canRunTasks = currentUser?.role !== "viewer";
  const canViewOnly = currentUser?.role === "viewer";
  const budgetExhausted =
    (currentUser?.budgetLimit ?? 0) > 0 &&
    (currentUser?.budgetLimit ?? 0) < 999999 &&
    (currentUser?.budgetSpent ?? 0) >= (currentUser?.budgetLimit ?? 0);
  const budgetPct =
    (currentUser?.budgetLimit ?? 0) > 0 && (currentUser?.budgetLimit ?? 0) < 999999
      ? Math.min(
          100,
          Math.round(
            ((currentUser?.budgetSpent ?? 0) / (currentUser?.budgetLimit ?? 1)) * 100
          )
        )
      : 0;

  return (
    <CurrentUserContext.Provider
      value={{
        currentUser,
        isLoading,
        isAuthenticated,
        login,
        logout,
        refresh,
        setRole,
        setBudgetSpent,
        isAdmin,
        isManager,
        canRunTasks,
        canViewOnly,
        budgetExhausted,
        budgetPct,
      }}
    >
      {children}
    </CurrentUserContext.Provider>
  );
}

export function useCurrentUser() {
  const ctx = useContext(CurrentUserContext);
  if (!ctx) throw new Error("useCurrentUser must be used within CurrentUserProvider");
  return ctx;
}

// ─── Role display helpers ─────────────────────────────────────────────────────

export const ROLE_LABELS: Record<UserRole, string> = {
  admin:   "Администратор",
  manager: "Менеджер",
  user:    "Пользователь",
  viewer:  "Наблюдатель",
};

export const ROLE_COLORS: Record<UserRole, { bg: string; text: string; border: string }> = {
  admin:   { bg: "bg-red-50 dark:bg-red-950/40",       text: "text-red-700 dark:text-red-400",       border: "border-red-200 dark:border-red-800" },
  manager: { bg: "bg-violet-50 dark:bg-violet-950/40", text: "text-violet-700 dark:text-violet-400", border: "border-violet-200 dark:border-violet-800" },
  user:    { bg: "bg-indigo-50 dark:bg-indigo-950/40", text: "text-indigo-700 dark:text-indigo-400", border: "border-indigo-200 dark:border-indigo-800" },
  viewer:  { bg: "bg-gray-100 dark:bg-gray-800",       text: "text-gray-600 dark:text-gray-400",     border: "border-gray-200 dark:border-gray-700" },
};
