// ARCANE UserSettingsPanel — "Warm Intelligence" design
// Shows current user's profile: role, budget progress, allowed tools.

import { useState } from "react";
import { cn } from "@/lib/utils";
import {
  useCurrentUser, ROLE_LABELS, ROLE_COLORS,
  type UserRole, type AllowedTool,
} from "@/contexts/CurrentUserContext";
import {
  X, User, Shield, Wallet, Wrench, ChevronLeft,
  AlertTriangle, Info,
  Globe, Terminal, FolderOpen, Image as ImageIcon, Plug, Server,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

// ─── Tool icon map ────────────────────────────────────────────────────────────

const TOOL_ICONS: Record<string, React.ReactNode> = {
  browser:  <Globe size={14} />,
  terminal: <Terminal size={14} />,
  ssh:      <Server size={14} />,
  files:    <FolderOpen size={14} />,
  images:   <ImageIcon size={14} />,
  api:      <Plug size={14} />,
};

// ─── Main Component ───────────────────────────────────────────────────────────

interface UserSettingsPanelProps {
  onClose: () => void;
}

export function UserSettingsPanel({ onClose }: UserSettingsPanelProps) {
  const { currentUser, setRole, budgetPct, budgetExhausted } = useCurrentUser();
  const [activeTab, setActiveTab] = useState<"profile" | "tools">("profile");

  if (!currentUser) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-gray-400">
        <span className="text-sm">Загрузка...</span>
      </div>
    );
  }

  const roleColors = ROLE_COLORS[currentUser.role];

  const tabs = [
    { id: "profile" as const, label: "Профиль",       icon: <User size={13} /> },
    { id: "tools"   as const, label: "Инструменты",   icon: <Wrench size={13} /> },
  ];

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#0f1117]">
      {/* Header */}
      <div className="h-14 border-b border-[#E8E6E1] dark:border-[#2a2d3a] flex items-center px-4 gap-3 shrink-0">
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <ChevronLeft size={15} />
        </button>
        <div className="flex-1">
          <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">Настройки пользователя</div>
          <div className="text-xs text-gray-400">{currentUser.email}</div>
        </div>
        {/* Role badge */}
        <div className={cn(
          "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border",
          roleColors.bg, roleColors.text, roleColors.border
        )}>
          <Shield size={10} />
          {ROLE_LABELS[currentUser.role]}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#E8E6E1] dark:border-[#2a2d3a] shrink-0 px-1">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-3 text-xs font-medium border-b-2 transition-colors",
              activeTab === tab.id
                ? "border-indigo-600 text-indigo-700 dark:text-indigo-400"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            )}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
          >
            {activeTab === "profile" && (
              <ProfileTab
                user={currentUser}
                budgetPct={budgetPct}
                budgetExhausted={budgetExhausted}
              />
            )}
            {activeTab === "tools" && (
              <ToolsTab tools={currentUser.allowedTools} />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

// ─── Profile Tab ──────────────────────────────────────────────────────────────

interface ProfileUser {
  name: string;
  email: string;
  role: UserRole;
  budgetLimit: number;
  budgetSpent: number;
  joinedAt: string;
  lastActive: string;
}

function ProfileTab({ user, budgetPct, budgetExhausted }: {
  user: ProfileUser;
  budgetPct: number;
  budgetExhausted: boolean;
}) {
  const roleColors = ROLE_COLORS[user.role];
  const budgetRemaining = Math.max(0, user.budgetLimit - user.budgetSpent);
  const hasLimit = user.budgetLimit > 0 && user.budgetLimit < 999999;

  return (
    <div className="p-4 space-y-5">
      {/* Avatar + name */}
      <div className="flex items-center gap-4 p-4 rounded-xl bg-gray-50 dark:bg-gray-800/50 border border-[#E8E6E1] dark:border-[#2a2d3a]">
        <div className={cn(
          "w-12 h-12 rounded-xl flex items-center justify-center text-lg font-bold shrink-0",
          roleColors.bg, roleColors.text
        )}>
          {user.name.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-gray-900 dark:text-gray-100 truncate">{user.name}</div>
          <div className="text-xs text-gray-500 dark:text-gray-400 truncate">{user.email}</div>
          {user.lastActive && (
            <div className="text-xs text-gray-400 mt-0.5">Активен: {user.lastActive}</div>
          )}
        </div>
      </div>

      {/* Role info */}
      <div className="space-y-2">
        <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Роль и права</div>
        <div className={cn(
          "flex items-start gap-3 p-3 rounded-xl border",
          roleColors.bg, roleColors.border
        )}>
          <Shield size={16} className={cn("mt-0.5 shrink-0", roleColors.text)} />
          <div>
            <div className={cn("text-sm font-semibold", roleColors.text)}>{ROLE_LABELS[user.role]}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              {user.role === "admin"   && "Полный доступ ко всем функциям и настройкам системы"}
              {user.role === "manager" && "Доступ к аналитике и управлению командой"}
              {user.role === "user"    && "Запуск задач через браузер и файлы"}
              {user.role === "viewer"  && "Только просмотр результатов"}
            </div>
          </div>
        </div>
      </div>

      {/* Budget */}
      <div className="space-y-2">
        <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Бюджет</div>
        {!hasLimit ? (
          <div className="flex items-center gap-2 p-3 rounded-xl bg-gray-50 dark:bg-gray-800/50 border border-[#E8E6E1] dark:border-[#2a2d3a]">
            <Wallet size={14} className="text-gray-400 shrink-0" />
            <span className="text-sm text-gray-500">Без ограничений</span>
          </div>
        ) : (
          <div className="p-3 rounded-xl bg-gray-50 dark:bg-gray-800/50 border border-[#E8E6E1] dark:border-[#2a2d3a] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Wallet size={14} className={budgetExhausted ? "text-red-500" : "text-green-500"} />
                <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
                  ${user.budgetSpent.toFixed(2)}
                  <span className="text-gray-400 font-normal"> / ${user.budgetLimit.toFixed(2)}</span>
                </span>
              </div>
              <span className={cn(
                "text-xs font-semibold px-2 py-0.5 rounded-full",
                budgetExhausted
                  ? "bg-red-100 dark:bg-red-950/50 text-red-600 dark:text-red-400"
                  : budgetPct >= 80
                  ? "bg-amber-100 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400"
                  : "bg-green-100 dark:bg-green-950/50 text-green-700 dark:text-green-400"
              )}>
                {budgetPct}%
              </span>
            </div>
            <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <motion.div
                className={cn(
                  "h-full rounded-full",
                  budgetExhausted ? "bg-red-500" : budgetPct >= 80 ? "bg-amber-500" : "bg-green-500"
                )}
                initial={{ width: 0 }}
                animate={{ width: `${budgetPct}%` }}
                transition={{ duration: 0.6, ease: "easeOut" }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-400">
              <span>Остаток: <span className="font-medium text-gray-600 dark:text-gray-300">${budgetRemaining.toFixed(2)}</span></span>
              {budgetExhausted && (
                <span className="text-red-500 font-medium flex items-center gap-1">
                  <AlertTriangle size={10} />
                  Исчерпан
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Info note */}
      <div className="flex items-start gap-2 p-3 rounded-xl bg-blue-50 dark:bg-blue-950/30 border border-blue-100 dark:border-blue-900/50">
        <Info size={13} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-xs text-blue-700 dark:text-blue-300 leading-relaxed">
          Для изменения роли или лимита бюджета обратитесь к администратору системы.
        </p>
      </div>
    </div>
  );
}

// ─── Tools Tab ────────────────────────────────────────────────────────────────

function ToolsTab({ tools }: { tools: AllowedTool[] }) {
  const enabledCount = tools.filter((t: AllowedTool) => t.enabled).length;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Доступные инструменты</div>
        <span className="text-xs text-gray-400">{enabledCount} из {tools.length} активны</span>
      </div>

      <div className="space-y-2">
        {tools.map((tool: AllowedTool) => (
          <div
            key={tool.id}
            className={cn(
              "flex items-center gap-3 p-3 rounded-xl border transition-colors",
              tool.enabled
                ? "bg-white dark:bg-gray-800/50 border-[#E8E6E1] dark:border-[#2a2d3a]"
                : "bg-gray-50 dark:bg-gray-900/50 border-gray-200 dark:border-gray-800 opacity-60"
            )}
          >
            <div className={cn(
              "w-8 h-8 rounded-lg flex items-center justify-center shrink-0",
              tool.enabled
                ? "bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400"
                : "bg-gray-100 dark:bg-gray-800 text-gray-400"
            )}>
              {TOOL_ICONS[tool.id] ?? <Wrench size={14} />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-gray-800 dark:text-gray-200">{tool.label}</div>
              <div className="text-xs text-gray-400 truncate">{tool.description}</div>
            </div>
            <div className={cn(
              "w-2 h-2 rounded-full shrink-0",
              tool.enabled ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"
            )} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Unused exports kept for compatibility ────────────────────────────────────
export { X }; // re-export to avoid unused import warning
