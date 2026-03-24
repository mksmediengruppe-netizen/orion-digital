// ORION PermissionDeniedScreen — "Warm Intelligence" design
// Full-panel permission denied state for various scenarios:
// - Admin dashboard access by non-admin
// - Budget exhausted (hard block)
// - Tool disabled by admin
// - Chat hidden by admin

import { cn } from "@/lib/utils";
import { ShieldOff, Lock, WalletCards, EyeOff, ArrowLeft, Mail } from "lucide-react";
import { motion } from "framer-motion";

export type PermissionDeniedReason =
  | "admin_only"
  | "budget_exhausted"
  | "tool_disabled"
  | "chat_hidden"
  | "viewer_role";

interface PermissionDeniedScreenProps {
  reason: PermissionDeniedReason;
  toolName?: string;         // for tool_disabled
  onBack?: () => void;
  onContactAdmin?: () => void;
  className?: string;
  compact?: boolean;         // for inline panel use (not full screen)
}

const CONFIGS: Record<PermissionDeniedReason, {
  icon: React.ReactNode;
  iconBg: string;
  title: string;
  description: string;
  actionLabel?: string;
  secondaryLabel?: string;
}> = {
  admin_only: {
    icon: <ShieldOff size={28} />,
    iconBg: "bg-red-50 dark:bg-red-950/40 text-red-500",
    title: "Нет доступа",
    description: "Этот раздел доступен только администраторам. Обратитесь к администратору для получения прав.",
    actionLabel: "Назад",
    secondaryLabel: "Написать администратору",
  },
  budget_exhausted: {
    icon: <WalletCards size={28} />,
    iconBg: "bg-orange-50 dark:bg-orange-950/40 text-orange-500",
    title: "Бюджет исчерпан",
    description: "Ваш месячный лимит использован полностью. Новые задачи заблокированы до пополнения бюджета администратором.",
    actionLabel: "Написать администратору",
  },
  tool_disabled: {
    icon: <Lock size={28} />,
    iconBg: "bg-gray-100 dark:bg-gray-800 text-gray-500",
    title: "Инструмент отключён",
    description: "Администратор отключил этот инструмент для вашего аккаунта. Обратитесь к администратору для получения доступа.",
    actionLabel: "Написать администратору",
  },
  chat_hidden: {
    icon: <EyeOff size={28} />,
    iconBg: "bg-gray-100 dark:bg-gray-800 text-gray-500",
    title: "Чат скрыт",
    description: "Этот чат скрыт администратором и недоступен для просмотра.",
    actionLabel: "Назад",
  },
  viewer_role: {
    icon: <ShieldOff size={28} />,
    iconBg: "bg-blue-50 dark:bg-blue-950/40 text-blue-500",
    title: "Только просмотр",
    description: "Ваша роль «Наблюдатель» позволяет только просматривать результаты. Для запуска задач необходима роль «Пользователь».",
    actionLabel: "Написать администратору",
  },
};

export function PermissionDeniedScreen({
  reason,
  toolName,
  onBack,
  onContactAdmin,
  className,
  compact = false,
}: PermissionDeniedScreenProps) {
  const config = CONFIGS[reason];

  const description = reason === "tool_disabled" && toolName
    ? `Администратор отключил инструмент «${toolName}» для вашего аккаунта. Обратитесь к администратору для получения доступа.`
    : config.description;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "p-6 h-full" : "p-12 min-h-[400px]",
        className
      )}
    >
      {/* Icon */}
      <div className={cn(
        "rounded-2xl flex items-center justify-center mb-5",
        compact ? "w-12 h-12" : "w-16 h-16",
        config.iconBg
      )}>
        <div className={compact ? "scale-75" : ""}>{config.icon}</div>
      </div>

      {/* Text */}
      <h3 className={cn(
        "font-semibold text-gray-900 dark:text-gray-100 mb-2",
        compact ? "text-base" : "text-xl"
      )}>
        {config.title}
      </h3>
      <p className={cn(
        "text-gray-500 dark:text-gray-400 max-w-sm leading-relaxed",
        compact ? "text-xs" : "text-sm"
      )}>
        {description}
      </p>

      {/* Actions */}
      <div className={cn("flex flex-col gap-2 mt-6", compact ? "w-full max-w-[200px]" : "w-full max-w-[240px]")}>
        {config.actionLabel && (
          <button
            onClick={config.actionLabel === "Назад" ? onBack : onContactAdmin}
            className={cn(
              "flex items-center justify-center gap-2 px-4 rounded-xl font-medium transition-all",
              compact ? "py-2 text-xs" : "py-2.5 text-sm",
              config.actionLabel === "Назад"
                ? "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
                : "bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm hover:shadow-md hover:-translate-y-0.5"
            )}
          >
            {config.actionLabel === "Назад" ? <ArrowLeft size={14} /> : <Mail size={14} />}
            {config.actionLabel}
          </button>
        )}
        {config.secondaryLabel && (
          <button
            onClick={onContactAdmin}
            className={cn(
              "flex items-center justify-center gap-2 px-4 rounded-xl font-medium transition-all",
              compact ? "py-2 text-xs" : "py-2.5 text-sm",
              "bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300"
            )}
          >
            <Mail size={14} />
            {config.secondaryLabel}
          </button>
        )}
      </div>

      {/* Error code for debugging */}
      <div className={cn("mt-4 font-mono text-gray-300 dark:text-gray-600", compact ? "text-[10px]" : "text-xs")}>
        403 · {reason}
      </div>
    </motion.div>
  );
}

// ─── Inline tool-disabled badge for Composer ─────────────────────────────────

interface ToolDisabledBadgeProps {
  toolName: string;
  className?: string;
}

export function ToolDisabledBadge({ toolName, className }: ToolDisabledBadgeProps) {
  return (
    <div className={cn(
      "flex items-center gap-1.5 px-2 py-1 rounded-md bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500 text-xs",
      className
    )}>
      <Lock size={10} />
      <span>{toolName} отключён</span>
    </div>
  );
}
