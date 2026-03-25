// ORION Admin Dashboard — "Warm Intelligence" design
// Full admin area: KPI cards, users table, tasks, golden paths

import { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { AdminStats, AdminUser, ChatSummary } from "@/lib/api";
import {
  ADMIN_TASKS, GOLDEN_PATHS
} from "@/lib/mockData";
import { StatusBadge } from "./StatusBadge";
import { useCurrentUser } from "@/contexts/CurrentUserContext";
import { PermissionDeniedScreen } from "@/components/orion/PermissionDeniedScreen";
import {
  Users, Activity, TrendingUp, TrendingDown, DollarSign, Clock,
  ShieldCheck, XCircle, Search, ChevronLeft, Star, LayoutDashboard,
  MessageSquare, ListChecks, Brain, AlertTriangle, BarChart2, Settings, Plus,
  Eye, EyeOff, Lock, Unlock, Edit2, Trash2, ChevronRight, ChevronDown,
  Globe, Terminal, FolderOpen, Image as ImageIcon, X, Check, Copy, RefreshCw,
  Key, Shield, UserPlus, MessageCircle, ToggleLeft, ToggleRight, Wallet
} from "lucide-react";

const ADMIN_SECTIONS = [
  { id: "dashboard",    label: "Dashboard",     icon: <LayoutDashboard size={14} /> },
  { id: "users",        label: "Пользователи",  icon: <Users size={14} /> },
  { id: "chats",        label: "Чаты",          icon: <MessageSquare size={14} /> },
  { id: "tasks",        label: "Задачи",        icon: <ListChecks size={14} /> },
  { id: "memory",       label: "Память",        icon: <Brain size={14} /> },
  { id: "golden",       label: "Golden Paths",  icon: <Star size={14} /> },
  { id: "antipatterns", label: "Anti-patterns", icon: <AlertTriangle size={14} /> },
  { id: "analytics",    label: "Аналитика",     icon: <BarChart2 size={14} /> },
  { id: "costs",        label: "Стоимость",     icon: <DollarSign size={14} /> },
  { id: "health",       label: "Здоровье",      icon: <Activity size={14} /> },
  { id: "multissh",    label: "MultiSSH",     icon: <Settings size={14} /> },
  { id: "evals",        label: "Эвалюации",    icon: <ShieldCheck size={14} /> },
  { id: "settings",     label: "Настройки",     icon: <Settings size={14} /> },
];

interface AdminDashboardProps {
  onBack: () => void;
  onRefillBudget?: (amount: number) => void;
}

export function AdminDashboard({ onBack, onRefillBudget }: AdminDashboardProps) {
  const [activeSection, setActiveSection] = useState("dashboard");
  const [searchQuery, setSearchQuery] = useState("");
  const { isAdmin, isManager } = useCurrentUser();

  // Role guard — only admin and manager can access the admin dashboard
  if (!isAdmin && !isManager) {
    return (
      <div className="flex h-full bg-[#F8F7F5] dark:bg-[#0a0c12]">
        {/* Minimal sidebar so user can go back */}
        <aside className="w-52 bg-white dark:bg-[#0f1117] border-r border-[#E8E6E1] dark:border-[#2a2d3a] flex flex-col shrink-0">
          <div className="h-14 border-b border-[#E8E6E1] dark:border-[#2a2d3a] flex items-center px-4 gap-2">
            <button
              onClick={onBack}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <ChevronLeft size={15} />
            </button>
            <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">Админка</span>
          </div>
        </aside>
        <div className="flex-1 flex items-center justify-center">
          <PermissionDeniedScreen
            reason="admin_only"
            onBack={onBack}
            onContactAdmin={() => {
              onBack();
            }}
          />
        </div>
      </div>
    );
  }

  // Escape key → go back
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onBack();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onBack]);

  return (
    <div className="flex h-full bg-[#F8F7F5]">
      {/* Admin sidebar */}
      <aside className="w-52 bg-white border-r border-[#E8E6E1] flex flex-col shrink-0">
        <div className="h-14 border-b border-[#E8E6E1] flex items-center px-4 gap-2">
          <button
            onClick={onBack}
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ChevronLeft size={15} />
          </button>
          <span className="text-sm font-semibold text-gray-900">Админка</span>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {ADMIN_SECTIONS.map(section => (
            <button
              key={section.id}
              onClick={() => setActiveSection(section.id)}
              className={cn(
                "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors text-left",
                activeSection === section.id
                  ? "bg-indigo-50 text-indigo-700 font-medium"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-800"
              )}
            >
              <span className={activeSection === section.id ? "text-indigo-600" : "text-gray-400"}>
                {section.icon}
              </span>
              {section.label}
            </button>
          ))}
        </nav>
      </aside>

      {/* Admin content */}
      <div className="flex-1 overflow-y-auto">
        {activeSection === "dashboard" && <DashboardSection />}
        {activeSection === "users" && <UsersSection searchQuery={searchQuery} setSearchQuery={setSearchQuery} onRefillBudget={onRefillBudget} />}
        {activeSection === "tasks" && <TasksSection searchQuery={searchQuery} setSearchQuery={setSearchQuery} />}
        {activeSection === "golden" && <GoldenPathsSection />}
        {activeSection === "memory" && <MemorySection />}
        {activeSection === "multissh" && <MultiSSHSection />}
        {activeSection === "evals" && <EvalsSection />}
        {activeSection === "chats" && <ChatsSection searchQuery={searchQuery} setSearchQuery={setSearchQuery} />}
        {activeSection === "antipatterns" && <AntiPatternsSection />}
        {activeSection === "analytics" && <AnalyticsSection />}
        {activeSection === "costs" && <CostsSection />}
        {activeSection === "health" && <HealthSection />}
        {activeSection === "settings" && <SettingsSection />}
        {(activeSection !== "dashboard" && activeSection !== "users" && activeSection !== "tasks" && activeSection !== "golden" && activeSection !== "memory" && activeSection !== "multissh" && activeSection !== "evals" && activeSection !== "chats" && activeSection !== "antipatterns" && activeSection !== "analytics" && activeSection !== "costs" && activeSection !== "health" && activeSection !== "settings") && (
          <ComingSoonSection label={ADMIN_SECTIONS.find(s => s.id === activeSection)?.label ?? ""} />
        )}
      </div>
    </div>
  );
}

// ─── Dashboard Section ───────────────────────────────────────────────────────

function DashboardSection() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.admin.stats().then(setStats).catch(console.error).finally(() => setLoading(false));
  }, []);

  const kpis = stats ? [
    { label: "Пользователи",     value: stats.total_users,   icon: <Users size={16} />,        color: "indigo", trend: "" },
    { label: "Активные задачи",  value: stats.active_tasks,  icon: <Activity size={16} />,     color: "green",  trend: "" },
    { label: "Успешность",       value: `${stats.success_rate}%`, icon: <TrendingUp size={16} />, color: "green", trend: "" },
    { label: "Fail Rate",        value: `${stats.fail_rate}%`, icon: <TrendingDown size={16} />, color: "red",   trend: "" },
    { label: "Общая стоимость",  value: `$${stats.total_cost}`, icon: <DollarSign size={16} />, color: "amber", trend: "" },
    { label: "Среднее время",    value: stats.avg_task_time,  icon: <Clock size={16} />,        color: "blue",   trend: "" },
    { label: "Verifier rejects", value: stats.verifier_rejects, icon: <ShieldCheck size={16} />, color: "purple", trend: "" },
    { label: "Judge rejects",    value: stats.judge_rejects, icon: <XCircle size={16} />,      color: "red",    trend: "" },
  ] : [];

  const colorMap: Record<string, { bg: string; icon: string; text: string }> = {
    indigo: { bg: "bg-indigo-50", icon: "text-indigo-600", text: "text-indigo-900" },
    green:  { bg: "bg-green-50",  icon: "text-green-600",  text: "text-green-900" },
    red:    { bg: "bg-red-50",    icon: "text-red-600",    text: "text-red-900" },
    amber:  { bg: "bg-amber-50",  icon: "text-amber-600",  text: "text-amber-900" },
    blue:   { bg: "bg-blue-50",   icon: "text-blue-600",   text: "text-blue-900" },
    purple: { bg: "bg-purple-50", icon: "text-purple-600", text: "text-purple-900" },
  };

  if (loading) return <div className="p-6 text-sm text-gray-400 animate-pulse">Загрузка статистики...</div>;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">Обзор системы ORION</p>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {kpis.map((kpi, i) => {
          const colors = colorMap[kpi.color];
          return (
            <div key={i} className="bg-white rounded-xl border border-[#E8E6E1] p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-500">{kpi.label}</span>
                <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center", colors.bg)}>
                  <span className={colors.icon}>{kpi.icon}</span>
                </div>
              </div>
              <div className={cn("text-2xl font-bold", colors.text)}>{kpi.value}</div>
              <div className="text-[11px] text-gray-400">
                <span className={kpi.trend.startsWith("+") ? "text-green-600" : kpi.trend.startsWith("-") && kpi.color === "red" ? "text-green-600" : "text-gray-400"}>
                  {kpi.trend}
                </span>
                {" "}за сегодня
              </div>
            </div>
          );
        })}
      </div>

      {/* Recent chats from real API */}
      {stats && stats.recent_chats && stats.recent_chats.length > 0 && (
        <div className="bg-white rounded-xl border border-[#E8E6E1] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#E8E6E1] flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-800">Последние задачи</span>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#E8E6E1] bg-[#F8F7F5]">
                <th className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-2">Задача</th>
                <th className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-2">Пользователь</th>
                <th className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-2">Статус</th>
                <th className="text-right text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-2">Стоимость</th>
              </tr>
            </thead>
            <tbody>
              {stats.recent_chats.map((chat: any) => (
                <tr key={chat.id} className="border-b border-[#E8E6E1] last:border-0 hover:bg-[#F8F7F5] transition-colors">
                  <td className="px-4 py-3">
                    <div className="text-sm font-medium text-gray-800">{chat.title}</div>
                    <div className="text-[11px] text-gray-400">{chat.model ?? '—'}</div>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{chat.user ?? chat.user_id ?? '—'}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={chat.status as any} size="sm" />
                  </td>
                  <td className="px-4 py-3 text-right text-sm font-mono text-gray-700">${(chat.cost ?? 0).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Users Section ───────────────────────────────────────────────────────────

// ─── Full User Management Types ──────────────────────────────────────────────

interface ManagedUser {
  id: string;
  name: string;
  email: string;
  login: string;
  password: string;
  role: "admin" | "manager" | "user";
  tasks: number;
  cost: number;
  budgetLimit: number;
  lastActive: string;
  active: boolean;
  permissions: {
    browser: boolean;
    ssh: boolean;
    files: boolean;
    images: boolean;
    search: boolean;
    codeExecution: boolean;
    apiAccess: boolean;
  };
  hiddenChats: Set<string>;
  notifyOnBudget: boolean;
  adminEmail: string;
}

const INITIAL_USERS: ManagedUser[] = [
  {
    id: "u1", name: "Алексей Петров", email: "alex@company.ru", login: "alex.petrov", password: "••••••••",
    role: "admin", tasks: 45, cost: 38.20, budgetLimit: 200, lastActive: "сейчас", active: true,
    permissions: { browser: true, ssh: true, files: true, images: true, search: true, codeExecution: true, apiAccess: true },
    hiddenChats: new Set(), notifyOnBudget: true, adminEmail: "admin@company.ru",
  },
  {
    id: "u2", name: "Мария Сидорова", email: "maria@company.ru", login: "maria.s", password: "••••••••",
    role: "user", tasks: 23, cost: 19.40, budgetLimit: 50, lastActive: "1 час назад", active: true,
    permissions: { browser: true, ssh: false, files: true, images: false, search: true, codeExecution: false, apiAccess: false },
    hiddenChats: new Set(), notifyOnBudget: true, adminEmail: "admin@company.ru",
  },
  {
    id: "u3", name: "Дмитрий Козлов", email: "dmitry@company.ru", login: "d.kozlov", password: "••••••••",
    role: "user", tasks: 67, cost: 54.10, budgetLimit: 100, lastActive: "вчера", active: true,
    permissions: { browser: true, ssh: true, files: true, images: true, search: true, codeExecution: true, apiAccess: false },
    hiddenChats: new Set(["c2"]), notifyOnBudget: false, adminEmail: "admin@company.ru",
  },
  {
    id: "u4", name: "Анна Новикова", email: "anna@company.ru", login: "a.novikova", password: "••••••••",
    role: "user", tasks: 12, cost: 8.90, budgetLimit: 30, lastActive: "3 дня назад", active: false,
    permissions: { browser: false, ssh: false, files: true, images: false, search: true, codeExecution: false, apiAccess: false },
    hiddenChats: new Set(), notifyOnBudget: true, adminEmail: "admin@company.ru",
  },
  {
    id: "u5", name: "Сергей Волков", email: "sergey@company.ru", login: "s.volkov", password: "••••••••",
    role: "manager", tasks: 31, cost: 22.20, budgetLimit: 150, lastActive: "неделю назад", active: true,
    permissions: { browser: true, ssh: true, files: true, images: true, search: true, codeExecution: false, apiAccess: true },
    hiddenChats: new Set(), notifyOnBudget: true, adminEmail: "admin@company.ru",
  },
];

const MOCK_USER_CHATS: Record<string, { id: string; title: string; status: string; cost: number; date: string }[]> = {
  u1: [
    { id: "c1", title: "Установка Bitrix на сервер", status: "executing", cost: 1.24, date: "сегодня" },
    { id: "c3", title: "Оптимизация скорости сайта", status: "completed", cost: 0.12, date: "вчера" },
  ],
  u2: [
    { id: "c2", title: "Настройка SSL сертификата", status: "completed", cost: 0.38, date: "сегодня" },
  ],
  u3: [
    { id: "c4", title: "Миграция WordPress", status: "thinking", cost: 0.67, date: "сегодня" },
    { id: "c5", title: "SEO аудит сайта", status: "failed", cost: 0.12, date: "вчера" },
    { id: "c6", title: "Оптимизация базы данных", status: "completed", cost: 0.89, date: "3 дня назад" },
  ],
  u4: [
    { id: "c7", title: "Настройка почты", status: "completed", cost: 0.21, date: "неделю назад" },
  ],
  u5: [
    { id: "c8", title: "Аудит безопасности", status: "completed", cost: 1.45, date: "вчера" },
    { id: "c9", title: "Настройка резервного копирования", status: "needs_review", cost: 0.54, date: "сегодня" },
  ],
};

const PERMISSION_LABELS: Record<keyof ManagedUser["permissions"], string> = {
  browser: "Браузер",
  ssh: "SSH / Терминал",
  files: "Файлы",
  images: "Изображения",
  search: "Поиск",
  codeExecution: "Выполнение кода",
  apiAccess: "API доступ",
};

const STATUS_COLORS: Record<string, string> = {
  executing: "bg-blue-50 text-blue-700",
  completed: "bg-green-50 text-green-700",
  thinking: "bg-amber-50 text-amber-700",
  failed: "bg-red-50 text-red-700",
  needs_review: "bg-yellow-50 text-yellow-700",
};

function UserEditModal({
  user,
  onSave,
  onClose,
}: {
  user: ManagedUser | null;
  onSave: (u: ManagedUser) => void;
  onClose: () => void;
}) {
  const isNew = !user;
  const [form, setForm] = useState<ManagedUser>(
    user ?? {
      id: `u${Date.now()}`,
      name: "",
      email: "",
      login: "",
      password: "",
      role: "user",
      tasks: 0,
      cost: 0,
      budgetLimit: 50,
      lastActive: "только что",
      active: true,
      permissions: { browser: true, ssh: false, files: true, images: false, search: true, codeExecution: false, apiAccess: false },
      hiddenChats: new Set(),
      notifyOnBudget: true,
      adminEmail: "admin@company.ru",
    }
  );
  const [showPassword, setShowPassword] = useState(false);
  const [tab, setTab] = useState<"info" | "permissions" | "budget">("info");

  const togglePermission = (key: keyof ManagedUser["permissions"]) => {
    setForm(prev => ({ ...prev, permissions: { ...prev.permissions, [key]: !prev.permissions[key] } }));
  };

  const handleSave = () => {
    if (!form.name.trim() || !form.login.trim()) return;
    onSave(form);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-[520px] max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E8E6E1]">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center">
              <UserPlus size={14} className="text-indigo-600" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-gray-900">{isNew ? "Новый пользователь" : `Редактировать: ${user?.name}`}</h2>
              <p className="text-[11px] text-gray-400">Заполните данные и настройте права</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 transition-colors">
            <X size={14} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[#E8E6E1] px-6">
          {(["info", "permissions", "budget"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 py-2.5 text-xs font-medium border-b-2 transition-colors",
                tab === t ? "border-indigo-500 text-indigo-700" : "border-transparent text-gray-500 hover:text-gray-700"
              )}
            >
              {t === "info" ? "Данные" : t === "permissions" ? "Разрешения" : "Бюджет"}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === "info" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Имя</label>
                  <input
                    value={form.name}
                    onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                    placeholder="Иван Иванов"
                    className="mt-1 w-full px-3 py-2 text-sm border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Email</label>
                  <input
                    value={form.email}
                    onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                    placeholder="user@company.ru"
                    className="mt-1 w-full px-3 py-2 text-sm border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Логин</label>
                  <input
                    value={form.login}
                    onChange={e => setForm(p => ({ ...p, login: e.target.value }))}
                    placeholder="ivan.ivanov"
                    className="mt-1 w-full px-3 py-2 text-sm border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300 font-mono"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Пароль</label>
                  <div className="relative mt-1">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={form.password === "••••••••" ? "" : form.password}
                      onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
                      placeholder={isNew ? "Введите пароль" : "Оставьте пустым чтобы не менять"}
                      className="w-full px-3 py-2 pr-9 text-sm border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300 font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(v => !v)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showPassword ? <EyeOff size={13} /> : <Eye size={13} />}
                    </button>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Роль</label>
                  <select
                    value={form.role}
                    onChange={e => setForm(p => ({ ...p, role: e.target.value as ManagedUser["role"] }))}
                    className="mt-1 w-full px-3 py-2 text-sm border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300 bg-white"
                  >
                    <option value="user">Пользователь</option>
                    <option value="manager">Менеджер</option>
                    <option value="admin">Администратор</option>
                  </select>
                </div>
                <div>
                  <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Статус</label>
                  <div className="mt-1 flex items-center gap-3 h-9">
                    <button
                      onClick={() => setForm(p => ({ ...p, active: !p.active }))}
                      className={cn(
                        "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                        form.active ? "bg-green-50 text-green-700 hover:bg-green-100" : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                      )}
                    >
                      {form.active ? <Check size={11} /> : <X size={11} />}
                      {form.active ? "Активен" : "Заблокирован"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {tab === "permissions" && (
            <div className="space-y-2">
              <p className="text-xs text-gray-500 mb-3">Выберите инструменты, доступные этому пользователю</p>
              {(Object.keys(PERMISSION_LABELS) as (keyof ManagedUser["permissions"])[]).map(key => (
                <div
                  key={key}
                  className={cn(
                    "flex items-center justify-between px-4 py-3 rounded-xl border transition-colors cursor-pointer",
                    form.permissions[key]
                      ? "border-indigo-200 bg-indigo-50"
                      : "border-[#E8E6E1] bg-white hover:bg-gray-50"
                  )}
                  onClick={() => togglePermission(key)}
                >
                  <div className="flex items-center gap-2.5">
                    <div className={cn(
                      "w-6 h-6 rounded-lg flex items-center justify-center",
                      form.permissions[key] ? "bg-indigo-100" : "bg-gray-100"
                    )}>
                      {key === "browser" && <Globe size={12} className={form.permissions[key] ? "text-indigo-600" : "text-gray-400"} />}
                      {key === "ssh" && <Terminal size={12} className={form.permissions[key] ? "text-indigo-600" : "text-gray-400"} />}
                      {key === "files" && <FolderOpen size={12} className={form.permissions[key] ? "text-indigo-600" : "text-gray-400"} />}
                      {key === "images" && <ImageIcon size={12} className={form.permissions[key] ? "text-indigo-600" : "text-gray-400"} />}
                      {key === "search" && <Search size={12} className={form.permissions[key] ? "text-indigo-600" : "text-gray-400"} />}
                      {key === "codeExecution" && <Terminal size={12} className={form.permissions[key] ? "text-indigo-600" : "text-gray-400"} />}
                      {key === "apiAccess" && <Key size={12} className={form.permissions[key] ? "text-indigo-600" : "text-gray-400"} />}
                    </div>
                    <span className="text-sm text-gray-700">{PERMISSION_LABELS[key]}</span>
                  </div>
                  <div className={cn(
                    "w-9 h-5 rounded-full transition-colors relative",
                    form.permissions[key] ? "bg-indigo-500" : "bg-gray-200"
                  )}>
                    <div className={cn(
                      "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                      form.permissions[key] ? "translate-x-4" : "translate-x-0.5"
                    )} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "budget" && (
            <div className="space-y-5">
              <div>
                <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Лимит бюджета (USD/месяц)</label>
                <div className="mt-2 flex items-center gap-3">
                  <span className="text-gray-400 text-sm">$</span>
                  <input
                    type="number"
                    min={0}
                    max={10000}
                    value={form.budgetLimit}
                    onChange={e => setForm(p => ({ ...p, budgetLimit: Number(e.target.value) }))}
                    className="flex-1 px-3 py-2 text-sm border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300 font-mono"
                  />
                </div>
                <input
                  type="range"
                  min={0}
                  max={500}
                  step={10}
                  value={form.budgetLimit}
                  onChange={e => setForm(p => ({ ...p, budgetLimit: Number(e.target.value) }))}
                  className="mt-3 w-full accent-indigo-500"
                />
                <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                  <span>$0</span><span>$100</span><span>$200</span><span>$300</span><span>$400</span><span>$500+</span>
                </div>
              </div>
              <div className="bg-[#F8F7F5] rounded-xl p-4 space-y-2">
                <div className="text-xs font-medium text-gray-600">Текущее использование</div>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-mono text-gray-800">${form.cost.toFixed(2)}</span>
                  <span className="text-xs text-gray-400">из ${form.budgetLimit}</span>
                </div>
                <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      form.cost / form.budgetLimit > 0.9 ? "bg-red-500" :
                      form.cost / form.budgetLimit > 0.7 ? "bg-amber-500" : "bg-indigo-500"
                    )}
                    style={{ width: `${Math.min(100, (form.cost / form.budgetLimit) * 100)}%` }}
                  />
                </div>
              <div className="text-[11px] text-gray-400">
                {((form.cost / form.budgetLimit) * 100).toFixed(0)}% использовано
              </div>
            </div>

            {/* Notification settings */}
            <div className="border border-[#E8E6E1] rounded-xl p-4 space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-amber-50 flex items-center justify-center">
                  <span className="text-amber-500 text-xs">🔔</span>
                </div>
                <span className="text-xs font-semibold text-gray-700">Уведомления по бюджету</span>
              </div>
              <div>
                <label className="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Адрес администратора</label>
                <input
                  type="email"
                  value={form.adminEmail}
                  onChange={e => setForm(p => ({ ...p, adminEmail: e.target.value }))}
                  placeholder="admin@company.ru"
                  className="mt-1 w-full px-3 py-2 text-sm border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300"
                />
                <p className="mt-1 text-[10px] text-gray-400">На этот адрес будет отправлено письмо при исчерпании бюджета</p>
              </div>
              <button
                type="button"
                onClick={() => setForm(p => ({ ...p, notifyOnBudget: !p.notifyOnBudget }))}
                className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg border border-[#E8E6E1] hover:bg-gray-50 transition-colors"
              >
                <div>
                  <div className="text-xs font-medium text-gray-700 text-left">Отправлять email при исчерпании</div>
                  <div className="text-[10px] text-gray-400 text-left">Администратор получит письмо как только бюджет закончится</div>
                </div>
                <div className={cn(
                  "w-9 h-5 rounded-full transition-colors relative shrink-0",
                  form.notifyOnBudget ? "bg-indigo-500" : "bg-gray-200"
                )}>
                  <div className={cn(
                    "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                    form.notifyOnBudget ? "translate-x-4" : "translate-x-0.5"
                  )} />
                </div>
              </button>
            </div>
          </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-[#E8E6E1]">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors">
            Отмена
          </button>
          <button
            onClick={handleSave}
            disabled={!form.name.trim() || !form.login.trim()}
            className="px-5 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isNew ? "Создать пользователя" : "Сохранить изменения"}
          </button>
        </div>
      </div>
    </div>
  );
}

function UserChatsModal({
  user,
  onClose,
}: {
  user: ManagedUser;
  onClose: () => void;
}) {
  const chats = MOCK_USER_CHATS[user.id] ?? [];
  const [hiddenChats, setHiddenChats] = useState<Set<string>>(new Set(user.hiddenChats));

  const toggleHide = (chatId: string) => {
    setHiddenChats(prev => {
      const next = new Set(prev);
      if (next.has(chatId)) next.delete(chatId);
      else next.add(chatId);
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-[480px] max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E8E6E1]">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Чаты пользователя</h2>
            <p className="text-[11px] text-gray-400">{user.name} · {chats.length} чатов</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 transition-colors">
            <X size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {chats.length === 0 ? (
            <div className="text-center py-8 text-sm text-gray-400">Нет чатов</div>
          ) : chats.map(chat => (
            <div
              key={chat.id}
              className={cn(
                "flex items-center gap-3 px-4 py-3 rounded-xl border transition-colors",
                hiddenChats.has(chat.id) ? "border-gray-100 bg-gray-50 opacity-60" : "border-[#E8E6E1] bg-white"
              )}
            >
              <MessageCircle size={14} className="text-gray-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className={cn("text-sm font-medium truncate", hiddenChats.has(chat.id) ? "text-gray-400 line-through" : "text-gray-800")}>
                  {chat.title}
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full font-medium", STATUS_COLORS[chat.status] ?? "bg-gray-100 text-gray-600")}>
                    {chat.status}
                  </span>
                  <span className="text-[10px] text-gray-400">${chat.cost} · {chat.date}</span>
                </div>
              </div>
              <button
                onClick={() => toggleHide(chat.id)}
                title={hiddenChats.has(chat.id) ? "Показать чат" : "Скрыть чат"}
                className={cn(
                  "p-1.5 rounded-lg transition-colors",
                  hiddenChats.has(chat.id)
                    ? "bg-gray-100 text-gray-400 hover:bg-gray-200"
                    : "hover:bg-red-50 text-gray-400 hover:text-red-500"
                )}
              >
                {hiddenChats.has(chat.id) ? <Eye size={13} /> : <EyeOff size={13} />}
              </button>
            </div>
          ))}
        </div>
        <div className="px-6 py-4 border-t border-[#E8E6E1] flex justify-between items-center">
          <p className="text-[11px] text-gray-400">
            {hiddenChats.size > 0 ? `${hiddenChats.size} чатов скрыто` : "Все чаты видны"}
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Готово
          </button>
        </div>
      </div>
    </div>
  );
}

function UsersSection({ searchQuery, setSearchQuery, onRefillBudget }: { searchQuery: string; setSearchQuery: (v: string) => void; onRefillBudget?: (amount: number) => void }) {
  const [refillInputs, setRefillInputs] = useState<Record<string, string>>({});
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingUser, setEditingUser] = useState<ManagedUser | null | "new">(null);
  const [viewingChats, setViewingChats] = useState<ManagedUser | null>(null);
  const [showPasswords, setShowPasswords] = useState<Set<string>>(new Set());

  // Load users from real API
  const loadUsers = useCallback(async () => {
    try {
      const resp = await api.admin.users();
      const data = (resp as any).users || resp || [];
      // Map API response to ManagedUser shape
      const mapped: ManagedUser[] = (data || []).map((u: any) => ({
        id: u.id,
        name: u.name || u.username || u.email,
        email: u.email || "",
        login: u.username || u.login || u.email,
        password: u.password || "••••••••",
        role: u.role || "user",
        tasks: u.task_count ?? u.tasks ?? 0,
        cost: u.total_cost ?? u.cost ?? 0,
        budgetLimit: u.budget_limit ?? u.budgetLimit ?? 50,
        lastActive: u.last_active || u.lastActive || "—",
        active: u.is_active ?? u.active ?? true,
        permissions: u.permissions || { browser: true, ssh: false, files: true, images: false, search: true, codeExecution: false, apiAccess: false },
        hiddenChats: new Set(u.hidden_chats || []),
        notifyOnBudget: u.notify_on_budget ?? true,
        adminEmail: u.admin_email || "",
      }));
      setUsers(mapped);
    } catch (e) {
      console.error("Failed to load users:", e);
      setUsers(INITIAL_USERS); // fallback to mock
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  const filtered = users.filter(u =>
    (u.name || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
    (u.email || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
    (u.login || "").toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleSave = async (u: ManagedUser) => {
    try {
      const isNew = !users.find(x => x.id === u.id);
      if (isNew) {
        await api.admin.createUser({ name: u.name, email: u.email, username: u.login, password: u.password, role: u.role, budget_limit: u.budgetLimit, permissions: u.permissions });
      } else {
        await api.admin.updateUser(u.id, { name: u.name, email: u.email, username: u.login, role: u.role, budget_limit: u.budgetLimit, permissions: u.permissions, is_active: u.active, ...(u.password && u.password !== '••••••••' ? { password: u.password } : {}) });
      }
      await loadUsers();
    } catch (e) {
      console.error("Failed to save user:", e);
      // Optimistic update as fallback
      setUsers(prev => {
        const idx = prev.findIndex(x => x.id === u.id);
        if (idx >= 0) { const next = [...prev]; next[idx] = u; return next; }
        return [...prev, u];
      });
    }
    setEditingUser(null);
  };

  const handleDelete = async (id: string) => {
    try {
      await api.admin.deleteUser(id);
      setUsers(prev => prev.filter(u => u.id !== id));
    } catch (e) {
      console.error("Failed to delete user:", e);
      setUsers(prev => prev.filter(u => u.id !== id));
    }
  };

  const togglePasswordVisibility = (id: string) => {
    setShowPasswords(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (loading) return <div className="p-6 text-sm text-gray-400 animate-pulse">Загрузка пользователей...</div>;

  return (
    <div className="p-6 space-y-4">
      {/* Modals */}
      {editingUser !== null && (
        <UserEditModal
          user={editingUser === "new" ? null : editingUser}
          onSave={handleSave}
          onClose={() => setEditingUser(null)}
        />
      )}
      {viewingChats && (
        <UserChatsModal
          user={viewingChats}
          onClose={() => setViewingChats(null)}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Пользователи</h1>
          <p className="text-sm text-gray-500 mt-0.5">{users.length} пользователей · {users.filter(u => u.active).length} активных</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder="Поиск..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1.5 text-sm bg-white border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300"
            />
          </div>
          <button
            onClick={() => setEditingUser("new")}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
          >
            <UserPlus size={13} />
            Добавить
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-[#E8E6E1] overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-[#F8F7F5]">
              {["Пользователь", "Логин / Пароль", "Роль", "Бюджет", "Разрешения", "Действия"].map(h => (
                <th key={h} className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-2.5">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(user => (
              <tr key={user.id} className={cn(
                "border-b border-[#E8E6E1] last:border-0 hover:bg-[#F8F7F5] transition-colors",
                !user.active && "opacity-60"
              )}>
                {/* User info */}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2.5">
                    <div className="relative">
                      <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center">
                        <span className="text-[10px] font-semibold text-indigo-700">
                          {(user.name || user.email || "U").split(" ").map(n => (n && n[0]) || "").join("")}
                        </span>
                      </div>
                      <div className={cn(
                        "absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white",
                        user.active ? "bg-green-400" : "bg-gray-300"
                      )} />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-800">{user.name || user.email || "Пользователь"}</div>
                      <div className="text-[11px] text-gray-400">{user.email}</div>
                    </div>
                  </div>
                </td>

                {/* Login / Password */}
                <td className="px-4 py-3">
                  <div className="space-y-0.5">
                    <div className="text-xs font-mono text-gray-700 flex items-center gap-1">
                      <Key size={10} className="text-gray-400" />
                      {user.login}
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-xs font-mono text-gray-400">
                        {showPasswords.has(user.id) ? user.password : "••••••••"}
                      </span>
                      <button
                        onClick={() => togglePasswordVisibility(user.id)}
                        className="p-0.5 rounded text-gray-300 hover:text-gray-500 transition-colors"
                      >
                        {showPasswords.has(user.id) ? <EyeOff size={10} /> : <Eye size={10} />}
                      </button>
                    </div>
                  </div>
                </td>

                {/* Role */}
                <td className="px-4 py-3">
                  <span className={cn(
                    "text-xs px-2 py-0.5 rounded-full font-medium",
                    user.role === "admin" ? "bg-indigo-50 text-indigo-700" :
                    user.role === "manager" ? "bg-amber-50 text-amber-700" :
                    "bg-gray-100 text-gray-600"
                  )}>
                    {user.role === "admin" ? "Администратор" : user.role === "manager" ? "Менеджер" : "Пользователь"}
                  </span>
                </td>

                {/* Budget */}
                <td className="px-4 py-3">
                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-mono text-gray-700">${user.cost.toFixed(2)}</span>
                      <span className="text-[10px] text-gray-400">/ ${user.budgetLimit}</span>
                    </div>
                    <div className="h-1.5 w-24 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all",
                          user.cost / user.budgetLimit >= 1 ? "bg-red-500" :
                          user.cost / user.budgetLimit > 0.9 ? "bg-red-400" :
                          user.cost / user.budgetLimit > 0.7 ? "bg-amber-500" : "bg-indigo-500"
                        )}
                        style={{ width: `${Math.min(100, (user.cost / user.budgetLimit) * 100)}%` }}
                      />
                    </div>
                    {user.cost / user.budgetLimit >= 0.8 && user.cost / user.budgetLimit < 1 && (
                      <div className="flex items-center gap-1 mt-0.5">
                        <span className="text-[9px] font-semibold text-amber-500 uppercase tracking-wide">⚠️ {Math.round((user.cost / user.budgetLimit) * 100)}%</span>
                        <span className="text-[9px] text-amber-400">предупреждение</span>
                      </div>
                    )}
                    {user.cost / user.budgetLimit >= 1 && (
                      <div className="flex flex-col gap-1 mt-1">
                        <span className="text-[9px] font-semibold text-red-500 uppercase tracking-wide">Исчерпан</span>
                        {onRefillBudget && (
                          <div className="flex items-center gap-1">
                            <span className="text-[9px] text-gray-400">$</span>
                            <input
                              type="number"
                              min="1"
                              max="9999"
                              step="1"
                              placeholder="0"
                              value={refillInputs[user.id] ?? ""}
                              onChange={e => setRefillInputs(prev => ({ ...prev, [user.id]: e.target.value }))}
                              onKeyDown={e => {
                                if (e.key === "Enter") {
                                  const amt = parseFloat(refillInputs[user.id] ?? "");
                                  if (!isNaN(amt) && amt > 0) {
                                    setUsers(prev => prev.map(u => u.id === user.id ? { ...u, cost: 0, budgetLimit: u.budgetLimit + amt } : u));
                                    onRefillBudget(amt);
                                    setRefillInputs(prev => ({ ...prev, [user.id]: "" }));
                                  }
                                }
                              }}
                              className="w-16 px-1.5 py-0.5 text-[10px] border border-gray-200 rounded bg-white text-gray-800 focus:outline-none focus:border-green-400 focus:ring-1 focus:ring-green-200"
                            />
                            <button
                              onClick={() => {
                                const amt = parseFloat(refillInputs[user.id] ?? "");
                                if (!isNaN(amt) && amt > 0) {
                                  setUsers(prev => prev.map(u => u.id === user.id ? { ...u, cost: 0, budgetLimit: u.budgetLimit + amt } : u));
                                  onRefillBudget(amt);
                                  setRefillInputs(prev => ({ ...prev, [user.id]: "" }));
                                }
                              }}
                              disabled={!refillInputs[user.id] || parseFloat(refillInputs[user.id]) <= 0}
                              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-green-600 hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-[9px] font-semibold transition-colors"
                            >
                              <RefreshCw size={8} />
                              +
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </td>

                {/* Permissions */}
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {(Object.keys(user.permissions) as (keyof ManagedUser["permissions"])[]).map(key =>
                      user.permissions[key] ? (
                        <span
                          key={key}
                          title={PERMISSION_LABELS[key]}
                          className="w-5 h-5 rounded flex items-center justify-center bg-indigo-50 text-indigo-500"
                        >
                          {key === "browser" && <Globe size={10} />}
                          {key === "ssh" && <Terminal size={10} />}
                          {key === "files" && <FolderOpen size={10} />}
                          {key === "images" && <ImageIcon size={10} />}
                          {key === "search" && <Search size={10} />}
                          {key === "codeExecution" && <Terminal size={10} />}
                          {key === "apiAccess" && <Key size={10} />}
                        </span>
                      ) : null
                    )}
                  </div>
                </td>

                {/* Actions */}
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setViewingChats(user)}
                      title="Просмотр чатов"
                      className="p-1.5 rounded-lg hover:bg-indigo-50 text-gray-400 hover:text-indigo-600 transition-colors"
                    >
                      <MessageCircle size={13} />
                    </button>
                    <button
                      onClick={() => setEditingUser(user)}
                      title="Редактировать"
                      className="p-1.5 rounded-lg hover:bg-amber-50 text-gray-400 hover:text-amber-600 transition-colors"
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      onClick={() => handleDelete(user.id)}
                      title="Удалить"
                      className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-500 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Tasks Section ───────────────────────────────────────────────────────────

function TasksSection({ searchQuery, setSearchQuery }: { searchQuery: string; setSearchQuery: (v: string) => void }) {
  const filtered = ADMIN_TASKS.filter(t =>
    t.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Задачи</h1>
          <p className="text-sm text-gray-500 mt-0.5">{ADMIN_TASKS.length} задач</p>
        </div>
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Поиск..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="pl-8 pr-3 py-1.5 text-sm bg-white border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300"
          />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-[#E8E6E1] overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-[#F8F7F5]">
              {["Задача", "Пользователь", "Статус", "Модель", "Время", "Стоимость"].map(h => (
                <th key={h} className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-2.5">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(task => (
              <tr key={task.id} className="border-b border-[#E8E6E1] last:border-0 hover:bg-[#F8F7F5] transition-colors">
                <td className="px-4 py-3 text-sm font-medium text-gray-800">{task.title}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{task.user}</td>
                <td className="px-4 py-3"><StatusBadge status={task.status as any} size="sm" /></td>
                <td className="px-4 py-3 text-xs text-gray-500">{task.model}</td>
                <td className="px-4 py-3 text-xs font-mono text-gray-600">{task.duration}</td>
                <td className="px-4 py-3 text-sm font-mono text-gray-700">${task.cost}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Golden Paths Section ─────────────────────────────────────────────────────

function GoldenPathsSection() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Golden Paths</h1>
        <p className="text-sm text-gray-500 mt-0.5">Проверенные сценарии выполнения задач</p>
      </div>

      <div className="grid gap-3">
        {GOLDEN_PATHS.map(gp => (
          <div key={gp.id} className="bg-white rounded-xl border border-[#E8E6E1] p-4 flex items-center gap-4">
            <div className="w-9 h-9 rounded-lg bg-amber-50 flex items-center justify-center shrink-0">
              <Star size={16} className="text-amber-500" fill="currentColor" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-gray-800 font-mono">{gp.name}</div>
              <div className="text-xs text-gray-500 mt-0.5">Последнее использование: {gp.lastUsed}</div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-sm font-semibold text-gray-800">{gp.uses}×</div>
              <div className="text-xs text-gray-500">использований</div>
            </div>
            <div className="text-right shrink-0">
              <div className={cn(
                "text-sm font-semibold",
                gp.successRate >= 95 ? "text-green-600" : gp.successRate >= 85 ? "text-amber-600" : "text-red-600"
              )}>
                {gp.successRate}%
              </div>
              <div className="text-xs text-gray-500">успех</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ComingSoonSection({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <div className="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center mx-auto mb-3">
          <Settings size={20} className="text-gray-400" />
        </div>
        <div className="text-sm font-medium text-gray-700">{label}</div>
        <div className="text-xs text-gray-400 mt-1">Раздел в разработке</div>
      </div>
    </div>
  );
}

// ─── Memory Section ───────────────────────────────────────────────────────────

function MemorySection() {
  const memories = [
    { id: "m1", user: "Алексей Петров", key: "preferred_stack", value: "PHP 8.2 + MySQL 8 + Nginx", created: "2024-03-10", hits: 12 },
    { id: "m2", user: "Алексей Петров", key: "server_credentials", value: "root@185.22.xx.xx (SSH key)", created: "2024-03-12", hits: 8 },
    { id: "m3", user: "Алексей Петров", key: "bitrix_license", value: "Бизнес, ключ: BX-XXXX-XXXX", created: "2024-03-15", hits: 5 },
    { id: "m4", user: "Мария Иванова",  key: "preferred_cms",    value: "WordPress 6.4 + Elementor", created: "2024-03-08", hits: 7 },
    { id: "m5", user: "Мария Иванова",  key: "domain_registrar", value: "reg.ru, login: m.ivanova@...", created: "2024-03-09", hits: 3 },
  ];
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Память агента</h1>
        <p className="text-sm text-gray-500 mt-0.5">Долгосрочная память — факты, которые агент запомнил о пользователях</p>
      </div>
      <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-700 flex items-start gap-2">
        <Brain size={14} className="mt-0.5 shrink-0" />
        <span>Агент автоматически сохраняет важные факты из разговоров. Вы можете просматривать, редактировать и удалять записи.</span>
      </div>
      <div className="bg-white border border-[#E8E6E1] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-gray-50">
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Пользователь</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Ключ</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Значение</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Использований</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {memories.map(m => (
              <tr key={m.id} className={cn("border-b border-[#E8E6E1] hover:bg-gray-50 transition-colors", selected === m.id && "bg-indigo-50")}>
                <td className="px-4 py-3 text-gray-700 font-medium">{m.user}</td>
                <td className="px-4 py-3 font-mono text-xs text-indigo-700 bg-indigo-50/50">{m.key}</td>
                <td className="px-4 py-3 text-gray-600 max-w-[200px] truncate">{m.value}</td>
                <td className="px-4 py-3 text-gray-500 text-center">{m.hits}×</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setSelected(selected === m.id ? null : m.id)}
                    className="text-xs text-red-500 hover:text-red-700 transition-colors"
                  >
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── MultiSSH Section ─────────────────────────────────────────────────────────

function MultiSSHSection() {
  const [servers, setServers] = useState([
    { id: "s1", name: "Prod Server",  host: "185.22.xx.xx",  user: "root", status: "online" as const,  lastPing: "2s ago",  tasks: 3 },
    { id: "s2", name: "Dev Server",   host: "185.22.xx.xy",  user: "root", status: "online" as const,  lastPing: "5s ago",  tasks: 1 },
    { id: "s3", name: "Staging",      host: "185.22.xx.xz",  user: "ubuntu", status: "offline" as const, lastPing: "5m ago", tasks: 0 },
    { id: "s4", name: "Backup Store", host: "185.22.xx.xw",  user: "backup", status: "online" as const, lastPing: "12s ago", tasks: 0 },
  ]);
  const [showAdd, setShowAdd] = useState(false);
  const [newHost, setNewHost] = useState("");
  const [newName, setNewName] = useState("");

  const handleAdd = () => {
    if (!newHost.trim()) return;
    setServers(prev => [...prev, {
      id: `s${Date.now()}`, name: newName || newHost, host: newHost,
      user: "root", status: "online", lastPing: "just now", tasks: 0
    }]);
    setNewHost(""); setNewName(""); setShowAdd(false);
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">MultiSSH</h1>
          <p className="text-sm text-gray-500 mt-0.5">Управление SSH-серверами для агентов</p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          <Plus size={14} />
          Добавить сервер
        </button>
      </div>

      {showAdd && (
        <div className="bg-white border border-[#E8E6E1] rounded-xl p-4 space-y-3">
          <div className="text-sm font-semibold text-gray-800">Новый SSH-сервер</div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Название</label>
              <input
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="My Server"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Host / IP</label>
              <input
                value={newHost}
                onChange={e => setNewHost(e.target.value)}
                placeholder="185.22.xx.xx"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={handleAdd} className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 transition-colors">Добавить</button>
            <button onClick={() => setShowAdd(false)} className="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-xs font-medium hover:bg-gray-200 transition-colors">Отмена</button>
          </div>
        </div>
      )}

      <div className="grid gap-3">
        {servers.map(s => (
          <div key={s.id} className="bg-white border border-[#E8E6E1] rounded-xl p-4 flex items-center gap-4">
            <div className={cn(
              "w-2.5 h-2.5 rounded-full shrink-0",
              s.status === "online" ? "bg-green-500" : "bg-gray-300"
            )} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-gray-800">{s.name}</div>
              <div className="text-xs text-gray-500 font-mono">{s.user}@{s.host}</div>
            </div>
            <div className="text-right shrink-0">
              <div className={cn("text-xs font-medium", s.status === "online" ? "text-green-600" : "text-gray-400")}>
                {s.status === "online" ? "Online" : "Offline"}
              </div>
              <div className="text-[10px] text-gray-400">{s.lastPing}</div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-sm font-semibold text-gray-800">{s.tasks}</div>
              <div className="text-[10px] text-gray-400">задач</div>
            </div>
            <button
              onClick={() => setServers(prev => prev.filter(x => x.id !== s.id))}
              className="shrink-0 p-1.5 rounded-lg text-gray-300 hover:text-red-400 hover:bg-red-50 transition-colors"
            >
              <XCircle size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Evals Section ────────────────────────────────────────────────────────────

function EvalsSection() {
  const evals = [
    { id: "e1", name: "Bitrix Install Eval",   runs: 24, pass: 22, fail: 2,  avg_score: 94, last_run: "2024-03-20", status: "passing" as const },
    { id: "e2", name: "SSL Setup Eval",         runs: 18, pass: 17, fail: 1,  avg_score: 97, last_run: "2024-03-19", status: "passing" as const },
    { id: "e3", name: "WordPress Deploy Eval",  runs: 31, pass: 28, fail: 3,  avg_score: 90, last_run: "2024-03-18", status: "passing" as const },
    { id: "e4", name: "DB Migration Eval",      runs: 12, pass: 9,  fail: 3,  avg_score: 75, last_run: "2024-03-17", status: "failing" as const },
    { id: "e5", name: "Redis Config Eval",      runs: 8,  pass: 8,  fail: 0,  avg_score: 100, last_run: "2024-03-15", status: "passing" as const },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Эвалюации</h1>
          <p className="text-sm text-gray-500 mt-0.5">Автоматические тесты качества работы агента</p>
        </div>
        <button className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors">
          <Activity size={14} />
          Запустить все
        </button>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Всего тестов", value: evals.length, color: "indigo" },
          { label: "Проходят",     value: evals.filter(e => e.status === "passing").length, color: "green" },
          { label: "Падают",       value: evals.filter(e => e.status === "failing").length, color: "red" },
        ].map(stat => (
          <div key={stat.label} className={cn(
            "rounded-xl p-4 border",
            stat.color === "indigo" ? "bg-indigo-50 border-indigo-100" :
            stat.color === "green"  ? "bg-green-50 border-green-100" :
                                      "bg-red-50 border-red-100"
          )}>
            <div className={cn(
              "text-2xl font-bold",
              stat.color === "indigo" ? "text-indigo-700" :
              stat.color === "green"  ? "text-green-700" : "text-red-700"
            )}>{stat.value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Evals table */}
      <div className="bg-white border border-[#E8E6E1] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-gray-50">
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Название</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Статус</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Прогоны</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Оценка</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Последний запуск</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {evals.map(ev => (
              <tr key={ev.id} className="border-b border-[#E8E6E1] hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 font-medium text-gray-800">{ev.name}</td>
                <td className="px-4 py-3">
                  <span className={cn(
                    "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
                    ev.status === "passing" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                  )}>
                    <span className={cn("w-1.5 h-1.5 rounded-full", ev.status === "passing" ? "bg-green-500" : "bg-red-500")} />
                    {ev.status === "passing" ? "Проходит" : "Падает"}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600">
                  <span className="text-green-600 font-medium">{ev.pass}</span>
                  <span className="text-gray-400"> / </span>
                  <span className="text-red-500">{ev.fail} fail</span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-16 bg-gray-100 rounded-full h-1.5">
                      <div
                        className={cn("h-1.5 rounded-full", ev.avg_score >= 90 ? "bg-green-500" : ev.avg_score >= 75 ? "bg-amber-400" : "bg-red-400")}
                        style={{ width: `${ev.avg_score}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-gray-600">{ev.avg_score}%</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">{ev.last_run}</td>
                <td className="px-4 py-3">
                  <button className="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors">Запустить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Chats Section ────────────────────────────────────────────────────────────

function ChatsSection({ searchQuery, setSearchQuery }: { searchQuery: string; setSearchQuery: (v: string) => void }) {
  const [chats, setChats] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 50;

  const loadChats = (p: number, q: string) => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(p * PAGE_SIZE), ...(q ? { q } : {}) });
    fetch(`/api/admin/chats?${params}`, { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } })
      .then(r => r.json())
      .then(resp => { setChats(resp.chats || []); setTotal(resp.total || 0); })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadChats(0, searchQuery); setPage(0); }, [searchQuery]);

  const filtered = chats;

  if (loading && chats.length === 0) return <div className="p-6 text-sm text-gray-400 animate-pulse">Загрузка чатов...</div>;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Чаты</h1>
          <p className="text-sm text-gray-500 mt-0.5">{total} чатов всего · стр. {page + 1}/{Math.ceil(total / PAGE_SIZE) || 1}</p>
        </div>
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Поиск..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="pl-8 pr-3 py-1.5 text-sm bg-white border border-[#E8E6E1] rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-300"
          />
        </div>
      </div>
      <div className="bg-white rounded-xl border border-[#E8E6E1] overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-[#F8F7F5]">
              {["Чат", "Пользователь", "Проект", "Статус", "Сообщений", "Стоимость"].map(h => (
                <th key={h} className="text-left text-[11px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-2.5">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((chat: any) => (
              <tr key={chat.id} className="border-b border-[#E8E6E1] last:border-0 hover:bg-[#F8F7F5] transition-colors">
                <td className="px-4 py-3">
                  <div className="text-sm font-medium text-gray-800">{chat.title || 'Без названия'}</div>
                  <div className="text-[11px] text-gray-400">{chat.model || '—'} · {chat.duration || '—'}</div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{chat.user_name || chat.user_email || chat.user_id || '—'}</td>
                <td className="px-4 py-3 text-xs text-gray-500">{chat.variant || chat.model || '—'}</td>
                <td className="px-4 py-3"><StatusBadge status={(chat.status || 'idle') as any} size="sm" /></td>
                <td className="px-4 py-3 text-sm text-gray-600 text-center">{chat.message_count ?? 0}</td>
                <td className="px-4 py-3 text-sm font-mono text-gray-700">${(chat.total_cost ?? 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button onClick={() => { const p = Math.max(0, page - 1); setPage(p); loadChats(p, searchQuery); }} disabled={page === 0} className="px-3 py-1.5 text-sm rounded-lg border border-[#E8E6E1] disabled:opacity-40 hover:bg-[#F8F7F5]">← Назад</button>
          <span className="text-sm text-gray-500">{page + 1} / {Math.ceil(total / PAGE_SIZE)}</span>
          <button onClick={() => { const p = Math.min(Math.ceil(total / PAGE_SIZE) - 1, page + 1); setPage(p); loadChats(p, searchQuery); }} disabled={page >= Math.ceil(total / PAGE_SIZE) - 1} className="px-3 py-1.5 text-sm rounded-lg border border-[#E8E6E1] disabled:opacity-40 hover:bg-[#F8F7F5]">Вперёд →</button>
        </div>
      )}
    </div>
  );
}

// ─── Anti-patterns Section ────────────────────────────────────────────────────

function AntiPatternsSection() {
  const [patterns, setPatterns] = useState([
    { id: "ap1", name: "rm -rf /",            category: "Деструктивные",  severity: "critical", blocked: 42, description: "Рекурсивное удаление корневой директории" },
    { id: "ap2", name: "DROP TABLE",           category: "База данных",    severity: "critical", blocked: 17, description: "Удаление таблицы без резервной копии" },
    { id: "ap3", name: "chmod 777",            category: "Безопасность",   severity: "high",     blocked: 31, description: "Небезопасные права доступа к файлам" },
    { id: "ap4", name: "password в коде",      category: "Безопасность",   severity: "high",     blocked: 28, description: "Хранение паролей в открытом виде в коде" },
    { id: "ap5", name: "eval() с user input",  category: "Инъекции",       severity: "critical", blocked: 9,  description: "Выполнение пользовательского кода через eval" },
    { id: "ap6", name: "curl | bash",          category: "Деструктивные",  severity: "high",     blocked: 14, description: "Выполнение скриптов без проверки содержимого" },
    { id: "ap7", name: "git push --force",     category: "Git",            severity: "medium",   blocked: 23, description: "Принудительный push в защищённые ветки" },
    { id: "ap8", name: "SELECT *",             category: "База данных",    severity: "low",      blocked: 67, description: "Неоптимальные запросы без указания полей" },
  ]);

  const severityColor: Record<string, string> = {
    critical: "bg-red-100 text-red-700",
    high:     "bg-orange-100 text-orange-700",
    medium:   "bg-amber-100 text-amber-700",
    low:      "bg-gray-100 text-gray-600",
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Anti-patterns</h1>
          <p className="text-sm text-gray-500 mt-0.5">Запрещённые паттерны — агент не будет их выполнять</p>
        </div>
        <button className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors">
          <Plus size={14} />
          Добавить паттерн
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Всего паттернов", value: patterns.length, color: "indigo" },
          { label: "Критических",     value: patterns.filter(p => p.severity === "critical").length, color: "red" },
          { label: "Заблокировано",   value: patterns.reduce((a, p) => a + p.blocked, 0), color: "amber" },
          { label: "Категорий",       value: Array.from(new Set(patterns.map(p => p.category))).length, color: "green" },
        ].map(stat => (
          <div key={stat.label} className={cn(
            "rounded-xl p-4 border",
            stat.color === "indigo" ? "bg-indigo-50 border-indigo-100" :
            stat.color === "red"    ? "bg-red-50 border-red-100" :
            stat.color === "amber"  ? "bg-amber-50 border-amber-100" :
                                      "bg-green-50 border-green-100"
          )}>
            <div className={cn(
              "text-2xl font-bold",
              stat.color === "indigo" ? "text-indigo-700" :
              stat.color === "red"    ? "text-red-700" :
              stat.color === "amber"  ? "text-amber-700" : "text-green-700"
            )}>{stat.value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{stat.label}</div>
          </div>
        ))}
      </div>

      <div className="bg-white border border-[#E8E6E1] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-gray-50">
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Паттерн</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Категория</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Серьёзность</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">Заблокировано</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {patterns.map(p => (
              <tr key={p.id} className="border-b border-[#E8E6E1] last:border-0 hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3">
                  <div className="font-mono text-sm font-medium text-gray-800">{p.name}</div>
                  <div className="text-xs text-gray-400 mt-0.5">{p.description}</div>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">{p.category}</td>
                <td className="px-4 py-3">
                  <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium", severityColor[p.severity])}>
                    {p.severity}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm font-semibold text-red-600">{p.blocked}×</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setPatterns(prev => prev.filter(x => x.id !== p.id))}
                    className="text-xs text-red-400 hover:text-red-600 transition-colors"
                  >
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Analytics Section ────────────────────────────────────────────────────────

function AnalyticsSection() {
  const [analyticsData, setAnalyticsData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.analytics.get()
      .then(setAnalyticsData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Use real data if available, fallback to empty
  const dailyData = analyticsData?.daily_tasks || [];
  const maxTasks = dailyData.length > 0 ? Math.max(...dailyData.map((d: any) => d.tasks ?? d.count ?? 0)) : 1;
  const modelUsage = analyticsData?.model_usage || [];
  const topTasks = analyticsData?.top_tasks || [];

  if (loading) return <div className="p-6 text-sm text-gray-400 animate-pulse">Загрузка аналитики...</div>;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Аналитика</h1>
        <p className="text-sm text-gray-500 mt-0.5">Статистика использования за последние 7 дней</p>
      </div>

      {/* Bar chart */}
      <div className="bg-white border border-[#E8E6E1] rounded-xl p-5">
        <div className="text-sm font-semibold text-gray-800 mb-4">Задачи по дням</div>
        <div className="flex items-end gap-2 h-32">
          {dailyData.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-400">Нет данных</div>
          ) : dailyData.map((d: any) => (
            <div key={d.day || d.date} className="flex-1 flex flex-col items-center gap-1">
              <div className="text-[10px] text-gray-500 font-mono">{d.tasks ?? d.count ?? 0}</div>
              <div
                className="w-full rounded-t-md bg-indigo-500 transition-all"
                style={{ height: `${((d.tasks ?? d.count ?? 0) / maxTasks) * 100}%` }}
              />
              <div className="text-[10px] text-gray-400">{d.day || d.date}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Model usage */}
        <div className="bg-white border border-[#E8E6E1] rounded-xl p-5">
          <div className="text-sm font-semibold text-gray-800 mb-4">Использование моделей</div>
          <div className="space-y-3">
            {modelUsage.length === 0 ? (
              <div className="text-sm text-gray-400">Нет данных</div>
            ) : modelUsage.map((m: any, idx: number) => {
              const colors = ["bg-indigo-500", "bg-blue-400", "bg-purple-500", "bg-green-500", "bg-amber-500"];
              return (
                <div key={m.model || idx}>
                  <div className="flex justify-between text-xs text-gray-600 mb-1">
                    <span>{m.model}</span>
                    <span className="font-mono font-medium">{m.pct ?? m.percent ?? 0}%</span>
                  </div>
                  <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className={cn("h-full rounded-full", m.color || colors[idx % colors.length])} style={{ width: `${m.pct ?? m.percent ?? 0}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Top task types */}
        <div className="bg-white border border-[#E8E6E1] rounded-xl p-5">
          <div className="text-sm font-semibold text-gray-800 mb-4">Топ типов задач</div>
          <div className="space-y-2">
            {topTasks.length === 0 ? (
              <div className="text-sm text-gray-400">Нет данных</div>
            ) : topTasks.map((t: any, i: number) => (
              <div key={t.name || i} className="flex items-center gap-2.5">
                <span className="text-xs text-gray-400 w-4 text-right">{i + 1}</span>
                <div className="flex-1 text-xs text-gray-700">{t.name}</div>
                <span className="text-xs font-mono font-semibold text-indigo-600">{t.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Costs Section ────────────────────────────────────────────────────────────

function CostsSection() {
  const breakdown = [
    { user: "Алексей Петров",  tasks: 28, cost: 18.42, budget: 50.00, model: "Orion Standard" },
    { user: "Мария Иванова",   tasks: 19, cost: 11.20, budget: 30.00, model: "Orion Fast" },
    { user: "Дмитрий Сидоров", tasks: 12, cost: 9.80,  budget: 25.00, model: "Orion Pro" },
    { user: "Анна Козлова",    tasks: 7,  cost: 3.15,  budget: 20.00, model: "Orion Fast" },
  ];
  const totalCost = breakdown.reduce((a, b) => a + b.cost, 0);
  const totalBudget = breakdown.reduce((a, b) => a + b.budget, 0);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Стоимость</h1>
        <p className="text-sm text-gray-500 mt-0.5">Расходы по пользователям и моделям</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Потрачено (месяц)", value: `$${totalCost.toFixed(2)}`, color: "indigo" },
          { label: "Бюджет (месяц)",    value: `$${totalBudget.toFixed(2)}`, color: "green" },
          { label: "Остаток",           value: `$${(totalBudget - totalCost).toFixed(2)}`, color: "amber" },
        ].map(stat => (
          <div key={stat.label} className={cn(
            "rounded-xl p-4 border",
            stat.color === "indigo" ? "bg-indigo-50 border-indigo-100" :
            stat.color === "green"  ? "bg-green-50 border-green-100" :
                                      "bg-amber-50 border-amber-100"
          )}>
            <div className={cn(
              "text-2xl font-bold",
              stat.color === "indigo" ? "text-indigo-700" :
              stat.color === "green"  ? "text-green-700" : "text-amber-700"
            )}>{stat.value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{stat.label}</div>
          </div>
        ))}
      </div>

      <div className="bg-white border border-[#E8E6E1] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-[#E8E6E1] text-sm font-semibold text-gray-800">По пользователям</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-gray-50">
              {["Пользователь", "Задач", "Потрачено", "Бюджет", "Использовано"].map(h => (
                <th key={h} className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {breakdown.map(row => {
              const pct = Math.round((row.cost / row.budget) * 100);
              return (
                <tr key={row.user} className="border-b border-[#E8E6E1] last:border-0 hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-gray-800">{row.user}</td>
                  <td className="px-4 py-3 text-gray-600">{row.tasks}</td>
                  <td className="px-4 py-3 font-mono font-semibold text-gray-800">${row.cost.toFixed(2)}</td>
                  <td className="px-4 py-3 font-mono text-gray-500">${row.budget.toFixed(2)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 bg-gray-100 rounded-full h-1.5">
                        <div
                          className={cn("h-1.5 rounded-full", pct >= 80 ? "bg-red-400" : pct >= 60 ? "bg-amber-400" : "bg-green-400")}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-xs font-mono text-gray-500">{pct}%</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Health Section ───────────────────────────────────────────────────────────

function HealthSection() {
  const services = [
    { name: "Agent Core",        status: "healthy" as const, latency: "12ms",  uptime: "99.98%", last_check: "2s ago" },
    { name: "SSH Gateway",       status: "healthy" as const, latency: "45ms",  uptime: "99.95%", last_check: "5s ago" },
    { name: "Browser Service",   status: "healthy" as const, latency: "89ms",  uptime: "99.91%", last_check: "3s ago" },
    { name: "LLM Proxy",         status: "healthy" as const, latency: "230ms", uptime: "99.99%", last_check: "1s ago" },
    { name: "File Storage",      status: "degraded" as const, latency: "340ms", uptime: "98.20%", last_check: "8s ago" },
    { name: "Verifier Service",  status: "healthy" as const, latency: "55ms",  uptime: "99.87%", last_check: "4s ago" },
    { name: "Memory Store",      status: "healthy" as const, latency: "8ms",   uptime: "100%",   last_check: "2s ago" },
    { name: "Task Queue",        status: "offline" as const, latency: "—",     uptime: "95.10%", last_check: "2m ago" },
  ];

  const statusColor: Record<string, string> = {
    healthy:  "bg-green-500",
    degraded: "bg-amber-400",
    offline:  "bg-red-500",
  };
  const statusLabel: Record<string, string> = {
    healthy:  "Работает",
    degraded: "Деградация",
    offline:  "Недоступен",
  };
  const statusBg: Record<string, string> = {
    healthy:  "bg-green-100 text-green-700",
    degraded: "bg-amber-100 text-amber-700",
    offline:  "bg-red-100 text-red-700",
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Здоровье системы</h1>
        <p className="text-sm text-gray-500 mt-0.5">Статус всех сервисов в реальном времени</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Работают",    value: services.filter(s => s.status === "healthy").length,  color: "green" },
          { label: "Деградация",  value: services.filter(s => s.status === "degraded").length, color: "amber" },
          { label: "Недоступны",  value: services.filter(s => s.status === "offline").length,  color: "red" },
        ].map(stat => (
          <div key={stat.label} className={cn(
            "rounded-xl p-4 border",
            stat.color === "green" ? "bg-green-50 border-green-100" :
            stat.color === "amber" ? "bg-amber-50 border-amber-100" :
                                     "bg-red-50 border-red-100"
          )}>
            <div className={cn(
              "text-2xl font-bold",
              stat.color === "green" ? "text-green-700" :
              stat.color === "amber" ? "text-amber-700" : "text-red-700"
            )}>{stat.value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{stat.label}</div>
          </div>
        ))}
      </div>

      <div className="bg-white border border-[#E8E6E1] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#E8E6E1] bg-gray-50">
              {["Сервис", "Статус", "Задержка", "Uptime", "Последняя проверка"].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {services.map(s => (
              <tr key={s.name} className="border-b border-[#E8E6E1] last:border-0 hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className={cn("w-2 h-2 rounded-full shrink-0", statusColor[s.status])} />
                    <span className="font-medium text-gray-800">{s.name}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium", statusBg[s.status])}>
                    {statusLabel[s.status]}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-gray-600">{s.latency}</td>
                <td className="px-4 py-3 font-mono text-xs text-gray-600">{s.uptime}</td>
                <td className="px-4 py-3 text-xs text-gray-400">{s.last_check}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Settings Section ─────────────────────────────────────────────────────────

function SettingsSection() {
  const [settings, setSettings] = useState({
    maxBudgetPerTask: "5.00",
    maxTaskDuration: "30",
    autoVerify: true,
    requireApproval: false,
    allowSSH: true,
    allowBrowser: true,
    allowFileWrite: true,
    defaultModel: "standard",
    notifyOnComplete: true,
    notifyOnFail: true,
    retryOnFail: true,
    maxRetries: "3",
  });

  const toggle = (key: keyof typeof settings) => {
    setSettings(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Настройки</h1>
        <p className="text-sm text-gray-500 mt-0.5">Глобальные настройки системы ORION</p>
      </div>

      {/* Budget & Limits */}
      <div className="bg-white border border-[#E8E6E1] rounded-xl p-5 space-y-4">
        <div className="text-sm font-semibold text-gray-800 border-b border-[#E8E6E1] pb-3">Лимиты и бюджет</div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Макс. бюджет на задачу ($)</label>
            <input
              type="number"
              value={settings.maxBudgetPerTask}
              onChange={e => setSettings(prev => ({ ...prev, maxBudgetPerTask: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Макс. время задачи (мин)</label>
            <input
              type="number"
              value={settings.maxTaskDuration}
              onChange={e => setSettings(prev => ({ ...prev, maxTaskDuration: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Макс. попыток при ошибке</label>
            <input
              type="number"
              value={settings.maxRetries}
              onChange={e => setSettings(prev => ({ ...prev, maxRetries: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">Модель по умолчанию</label>
            <select
              value={settings.defaultModel}
              onChange={e => setSettings(prev => ({ ...prev, defaultModel: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400 bg-white"
            >
              <option value="fast">Orion Fast</option>
              <option value="standard">Orion Standard</option>
              <option value="pro">Orion Pro</option>
            </select>
          </div>
        </div>
      </div>

      {/* Toggles */}
      <div className="bg-white border border-[#E8E6E1] rounded-xl p-5 space-y-4">
        <div className="text-sm font-semibold text-gray-800 border-b border-[#E8E6E1] pb-3">Разрешения агента</div>
        {[
          { key: "autoVerify",      label: "Автоматическая верификация результатов" },
          { key: "requireApproval", label: "Требовать подтверждение перед выполнением" },
          { key: "allowSSH",        label: "Разрешить SSH-подключения" },
          { key: "allowBrowser",    label: "Разрешить управление браузером" },
          { key: "allowFileWrite",  label: "Разрешить запись файлов" },
          { key: "retryOnFail",     label: "Автоматически повторять при ошибке" },
          { key: "notifyOnComplete",label: "Уведомлять о завершении задачи" },
          { key: "notifyOnFail",    label: "Уведомлять об ошибках" },
        ].map(({ key, label }) => (
          <div key={key} className="flex items-center justify-between">
            <span className="text-sm text-gray-700">{label}</span>
            <button
              onClick={() => toggle(key as keyof typeof settings)}
              className={cn(
                "relative w-9 h-5 rounded-full transition-colors",
                settings[key as keyof typeof settings] ? "bg-indigo-600" : "bg-gray-200"
              )}
            >
              <span className={cn(
                "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                settings[key as keyof typeof settings] ? "translate-x-4" : "translate-x-0.5"
              )} />
            </button>
          </div>
        ))}
      </div>

      <div className="flex justify-end">
        <button className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors">
          Сохранить настройки
        </button>
      </div>
    </div>
  );
}
