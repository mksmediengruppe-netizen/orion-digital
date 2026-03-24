// ORION CurrentUserContext — "Warm Intelligence" design
// Provides the currently logged-in user's profile: role, budget, allowed tools.
// In production this would come from the auth/session API.

import { createContext, useContext, useState, type ReactNode } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type UserRole = "admin" | "manager" | "user" | "viewer";

export interface AllowedTool {
  id: string;
  label: string;
  icon: string;  // emoji shorthand for display
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
}

// ─── Default demo users (switchable in Settings) ─────────────────────────────

export const DEMO_USERS: Record<UserRole, CurrentUser> = {
  admin: {
    id: "u1",
    name: "Алексей Петров",
    email: "alex@company.ru",
    role: "admin",
    budgetLimit: 100,
    budgetSpent: 38.20,
    joinedAt: "01.01.2025",
    lastActive: "сейчас",
    allowedTools: [
      { id: "browser",  label: "Браузер",   icon: "🌐", enabled: true,  description: "Управление браузером, веб-поиск" },
      { id: "terminal", label: "Терминал",  icon: "⌨️", enabled: true,  description: "Выполнение shell-команд" },
      { id: "ssh",      label: "SSH",       icon: "🔐", enabled: true,  description: "Подключение к удалённым серверам" },
      { id: "files",    label: "Файлы",     icon: "📁", enabled: true,  description: "Чтение и запись файлов" },
      { id: "images",   label: "Изображения", icon: "🖼️", enabled: true, description: "Генерация и обработка изображений" },
      { id: "api",      label: "API-вызовы", icon: "🔌", enabled: true, description: "Запросы к внешним API" },
    ],
  },
  manager: {
    id: "u5",
    name: "Сергей Волков",
    email: "sergey@company.ru",
    role: "manager",
    budgetLimit: 50,
    budgetSpent: 22.20,
    joinedAt: "15.03.2025",
    lastActive: "неделю назад",
    allowedTools: [
      { id: "browser",  label: "Браузер",   icon: "🌐", enabled: true,  description: "Управление браузером, веб-поиск" },
      { id: "terminal", label: "Терминал",  icon: "⌨️", enabled: false, description: "Выполнение shell-команд" },
      { id: "ssh",      label: "SSH",       icon: "🔐", enabled: false, description: "Подключение к удалённым серверам" },
      { id: "files",    label: "Файлы",     icon: "📁", enabled: true,  description: "Чтение и запись файлов" },
      { id: "images",   label: "Изображения", icon: "🖼️", enabled: true, description: "Генерация и обработка изображений" },
      { id: "api",      label: "API-вызовы", icon: "🔌", enabled: true, description: "Запросы к внешним API" },
    ],
  },
  user: {
    id: "u2",
    name: "Мария Сидорова",
    email: "maria@company.ru",
    role: "user",
    budgetLimit: 5,
    budgetSpent: 4.80,
    joinedAt: "10.02.2025",
    lastActive: "1 час назад",
    allowedTools: [
      { id: "browser",  label: "Браузер",   icon: "🌐", enabled: true,  description: "Управление браузером, веб-поиск" },
      { id: "terminal", label: "Терминал",  icon: "⌨️", enabled: false, description: "Выполнение shell-команд" },
      { id: "ssh",      label: "SSH",       icon: "🔐", enabled: false, description: "Подключение к удалённым серверам" },
      { id: "files",    label: "Файлы",     icon: "📁", enabled: true,  description: "Чтение и запись файлов" },
      { id: "images",   label: "Изображения", icon: "🖼️", enabled: false, description: "Генерация и обработка изображений" },
      { id: "api",      label: "API-вызовы", icon: "🔌", enabled: false, description: "Запросы к внешним API" },
    ],
  },
  viewer: {
    id: "u6",
    name: "Наблюдатель",
    email: "viewer@company.ru",
    role: "viewer",
    budgetLimit: 0,
    budgetSpent: 0,
    joinedAt: "20.03.2025",
    lastActive: "сейчас",
    allowedTools: [
      { id: "browser",  label: "Браузер",   icon: "🌐", enabled: false, description: "Управление браузером, веб-поиск" },
      { id: "terminal", label: "Терминал",  icon: "⌨️", enabled: false, description: "Выполнение shell-команд" },
      { id: "ssh",      label: "SSH",       icon: "🔐", enabled: false, description: "Подключение к удалённым серверам" },
      { id: "files",    label: "Файлы",     icon: "📁", enabled: false, description: "Чтение и запись файлов" },
      { id: "images",   label: "Изображения", icon: "🖼️", enabled: false, description: "Генерация и обработка изображений" },
      { id: "api",      label: "API-вызовы", icon: "🔌", enabled: false, description: "Запросы к внешним API" },
    ],
  },
};

// ─── Context ──────────────────────────────────────────────────────────────────

interface CurrentUserContextValue {
  currentUser: CurrentUser;
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

export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<CurrentUser>(DEMO_USERS.admin);

  const setRole = (role: UserRole) => {
    setCurrentUser(DEMO_USERS[role]);
  };

  const setBudgetSpent = (amount: number) => {
    setCurrentUser(u => ({ ...u, budgetSpent: amount }));
  };

  const isAdmin = currentUser.role === "admin";
  const isManager = currentUser.role === "manager";
  const canRunTasks = currentUser.role !== "viewer";
  const canViewOnly = currentUser.role === "viewer";
  const budgetExhausted = currentUser.budgetLimit > 0 && currentUser.budgetSpent >= currentUser.budgetLimit;
  const budgetPct = currentUser.budgetLimit > 0
    ? Math.min(100, Math.round((currentUser.budgetSpent / currentUser.budgetLimit) * 100))
    : 0;

  return (
    <CurrentUserContext.Provider value={{
      currentUser, setRole, setBudgetSpent,
      isAdmin, isManager, canRunTasks, canViewOnly,
      budgetExhausted, budgetPct,
    }}>
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
  admin:   { bg: "bg-red-50 dark:bg-red-950/40",    text: "text-red-700 dark:text-red-400",    border: "border-red-200 dark:border-red-800" },
  manager: { bg: "bg-violet-50 dark:bg-violet-950/40", text: "text-violet-700 dark:text-violet-400", border: "border-violet-200 dark:border-violet-800" },
  user:    { bg: "bg-indigo-50 dark:bg-indigo-950/40", text: "text-indigo-700 dark:text-indigo-400", border: "border-indigo-200 dark:border-indigo-800" },
  viewer:  { bg: "bg-gray-100 dark:bg-gray-800",    text: "text-gray-600 dark:text-gray-400",   border: "border-gray-200 dark:border-gray-700" },
};
