// ORION StatusBadge — "Warm Intelligence" design
// Shows agent/step status with color-coded indicator
// needs_review uses a yellow warning triangle icon instead of a dot

import { cn } from "@/lib/utils";
import { AlertTriangle } from "lucide-react";
import type { AgentStatus, StepStatus } from "@/lib/mockData";

type Status = AgentStatus | StepStatus;

const STATUS_CONFIG: Record<string, {
  label: string;
  dot: string;
  bg: string;
  text: string;
  icon?: "warning";
}> = {
  idle:         { label: "Ожидание",       dot: "bg-gray-400",              bg: "bg-gray-100",   text: "text-gray-600" },
  thinking:     { label: "Думает",         dot: "bg-indigo-500 live-pulse", bg: "bg-indigo-50",  text: "text-indigo-700" },
  executing:    { label: "Выполняет",      dot: "bg-green-500 live-pulse",  bg: "bg-green-50",   text: "text-green-700" },
  searching:    { label: "Ищет",           dot: "bg-amber-500 live-pulse",  bg: "bg-amber-50",   text: "text-amber-700" },
  verifying:    { label: "Проверяет",      dot: "bg-blue-500 live-pulse",   bg: "bg-blue-50",    text: "text-blue-700" },
  waiting:      { label: "Ждёт ввода",     dot: "bg-orange-400",            bg: "bg-orange-50",  text: "text-orange-700" },
  completed:    { label: "Завершено",      dot: "bg-green-500",             bg: "bg-green-50",   text: "text-green-700" },
  failed:       { label: "Ошибка",         dot: "bg-red-500",               bg: "bg-red-50",     text: "text-red-700" },
  partial:      { label: "Частично",       dot: "bg-amber-500",             bg: "bg-amber-50",   text: "text-amber-700" },
  // needs_review — yellow warning triangle
  "needs review": { label: "На проверке", dot: "bg-yellow-400",            bg: "bg-yellow-50",  text: "text-yellow-700", icon: "warning" },
  needs_review:   { label: "На проверке", dot: "bg-yellow-400",            bg: "bg-yellow-50",  text: "text-yellow-700", icon: "warning" },
  // Step statuses
  queued:       { label: "В очереди",      dot: "bg-gray-400",              bg: "bg-gray-100",   text: "text-gray-600" },
  running:      { label: "Выполняется",    dot: "bg-green-500 live-pulse",  bg: "bg-green-50",   text: "text-green-700" },
  success:      { label: "Успешно",        dot: "bg-green-500",             bg: "bg-green-50",   text: "text-green-700" },
  warning:      { label: "Предупреждение", dot: "bg-amber-500",             bg: "bg-amber-50",   text: "text-amber-700" },
  skipped:      { label: "Пропущен",       dot: "bg-gray-300",              bg: "bg-gray-50",    text: "text-gray-500" },
};

interface StatusBadgeProps {
  status: Status;
  size?: "sm" | "md";
  showLabel?: boolean;
  className?: string;
}

export function StatusBadge({ status, size = "md", showLabel = true, className }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.idle;
  const iconSize = size === "sm" ? 10 : 11;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium",
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-xs",
        config.bg,
        config.text,
        className
      )}
    >
      {config.icon === "warning" ? (
        <AlertTriangle size={iconSize} className="shrink-0 text-yellow-500" />
      ) : (
        <span className={cn("rounded-full shrink-0", size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2", config.dot)} />
      )}
      {showLabel && config.label}
    </span>
  );
}

export function ModeBadge({ mode }: { mode: "fast" | "standard" | "premium" }) {
  const config = {
    fast:     { label: "Быстрый",  bg: "bg-sky-50",    text: "text-sky-700",    border: "border-sky-200" },
    standard: { label: "Стандарт", bg: "bg-gray-50",   text: "text-gray-700",   border: "border-gray-200" },
    premium:  { label: "Премиум",  bg: "bg-violet-50", text: "text-violet-700", border: "border-violet-200" },
  }[mode];

  return (
    <span className={cn("inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border", config.bg, config.text, config.border)}>
      {config.label}
    </span>
  );
}

export function CostBadge({ cost }: { cost: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-gray-500 font-mono">
      <span className="text-gray-400">$</span>
      <span className="font-medium text-gray-700">{cost.toFixed(2)}</span>
    </span>
  );
}
