// ORION ChatHeader — model selector + status + timer + controls
// Layout: [breadcrumb] ... [$cost] [timer] [model▾] [status] [panel] [⋯]

import { cn } from "@/lib/utils";
import { type AgentStatus } from "@/lib/mockData";
import { PanelRight, MoreHorizontal, DollarSign, Clock, Square, Zap, Gauge, Sparkles, Crown, ChevronDown, Check, AlertTriangle, Terminal, Keyboard } from "lucide-react";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuTrigger, DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { useState } from "react";

const STATUS_LABELS: Record<AgentStatus, string> = {
  idle: "Ожидает",
  thinking: "Думает...",
  executing: "Выполняет",
  searching: "Ищет...",
  verifying: "Проверяет",
  waiting: "Ожидает ввода",
  completed: "Завершено",
  failed: "Ошибка",
  partial: "Частично",
  needs_review: "На проверке",
};

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: "bg-gray-300",
  thinking: "bg-amber-400 animate-pulse",
  executing: "bg-indigo-500 animate-pulse",
  searching: "bg-blue-400 animate-pulse",
  verifying: "bg-purple-400 animate-pulse",
  waiting: "bg-yellow-400",
  completed: "bg-green-500",
  failed: "bg-red-500",
  partial: "bg-orange-400",
  needs_review: "bg-yellow-400",
};

export type ModelKey = "mini" | "standard" | "sonnet" | "opus";

export interface ModelDef {
  label: string;
  sublabel: string;
  icon: React.ReactNode;
  iconColor: string;
  badgeColor: string;
  model: string;
  pricePerTask: string;
  budget: string;
  speed: string;
  desc: string;
}

export const MODELS: Record<ModelKey, ModelDef> = {
  mini: {
    label: "Быстрый",
    sublabel: "Fast",
    icon: <Zap size={11} />,
    iconColor: "text-amber-500",
    badgeColor: "bg-amber-50 border-amber-200 text-amber-700",
    model: "GPT-5.4 Mini",
    pricePerTask: "~$0.01",
    budget: "Лимит $2",
    speed: "⚡ Очень быстро",
    desc: "Простые задачи, тесты, MVP",
  },
  standard: {
    label: "Стандарт",
    sublabel: "Standard",
    icon: <Gauge size={11} />,
    iconColor: "text-blue-500",
    badgeColor: "bg-blue-50 border-blue-200 text-blue-700",
    model: "GPT-5.4",
    pricePerTask: "~$0.03",
    budget: "Лимит $5",
    speed: "🔥 Быстро",
    desc: "Большинство задач",
  },
  sonnet: {
    label: "Про",
    sublabel: "Pro",
    icon: <Sparkles size={11} />,
    iconColor: "text-violet-500",
    badgeColor: "bg-violet-50 border-violet-200 text-violet-700",
    model: "Claude Sonnet 4.6",
    pricePerTask: "~$0.08",
    budget: "Лимит $10",
    speed: "💎 Качественно",
    desc: "Сложные задачи, код, анализ",
  },
  opus: {
    label: "Премиум",
    sublabel: "Premium",
    icon: <Crown size={11} />,
    iconColor: "text-rose-500",
    badgeColor: "bg-rose-50 border-rose-200 text-rose-700",
    model: "Claude Opus 4",
    pricePerTask: "~$0.12",
    budget: "Лимит $25",
    speed: "👑 Максимум",
    desc: "Наивысшее качество",
  },
};

function exportChatMarkdown(chatTitle: string, projectName: string) {
  const content = `# ${chatTitle}\n\n**Проект:** ${projectName}\n**Экспортировано:** ${new Date().toLocaleString('ru')}\n\n---\n\n*Экспорт чата ORION*\n`;
  const blob = new Blob([content], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${chatTitle.replace(/[^а-яёa-z0-9]/gi, '_')}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

interface ChatHeaderProps {
  chatTitle: string;
  projectName: string;
  status: AgentStatus;
  rightPanelOpen: boolean;
  onToggleRightPanel: () => void;
  onStop?: () => void;
  cost?: number;
  duration?: string;
  isTimerLive?: boolean;
  model?: ModelKey;
  onModelChange?: (m: ModelKey) => void;
  onCommandPalette?: () => void;
  isTakeover?: boolean;
  onTakeoverActivate?: () => void;
  onTakeoverDeactivate?: () => void;
  isRunning?: boolean;

}

export function ChatHeader({
  chatTitle,
  projectName,
  status,
  rightPanelOpen,
  onToggleRightPanel,
  onStop,
  cost,
  duration,
  isTimerLive = false,
  model = "standard",
  onModelChange,
  onCommandPalette,
  isTakeover = false,
  onTakeoverActivate,
  onTakeoverDeactivate,
  isRunning = false,

}: ChatHeaderProps) {
  const [modelOpen, setModelOpen] = useState(false);
  const current = MODELS[model];

  return (
    <header className="h-12 border-b border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-[#0f1117] flex items-center px-4 gap-2 shrink-0">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-sm min-w-0 flex-1">
        <span className="text-gray-400 dark:text-gray-500 text-xs truncate max-w-[100px]">{projectName}</span>
        <span className="text-gray-300 dark:text-gray-600 text-xs">/</span>
        <span className="font-medium text-gray-900 dark:text-gray-100 truncate text-sm">{chatTitle}</span>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-1.5 shrink-0">
        {/* Cost */}
        {cost !== undefined && cost > 0 && (
          <div className="flex items-center gap-1 text-xs text-gray-500 hidden md:flex">
            <DollarSign size={11} className="text-green-500" />
            <span className="font-mono font-medium text-gray-700">{cost.toFixed(2)}</span>
          </div>
        )}

        {/* Duration */}
        {duration && (
          <div className="flex items-center gap-1 text-xs hidden md:flex">
            {isTimerLive
              ? <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse shrink-0" />
              : <Clock size={11} className="text-gray-400" />
            }
            <span className={cn(
              "font-mono tabular-nums",
              isTimerLive ? "text-indigo-600 font-semibold" : "text-gray-600"
            )}>{duration}</span>
          </div>
        )}

        {/* Model selector — compact pill in header */}
        <DropdownMenu open={modelOpen} onOpenChange={setModelOpen}>
          <DropdownMenuTrigger asChild>
            <button className={cn(
              "flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium border transition-colors",
              current.badgeColor,
              "hover:opacity-90"
            )}>
              <span className={current.iconColor}>{current.icon}</span>
              <span>{current.label}</span>
              <ChevronDown size={9} className="opacity-60" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-72 p-1.5" sideOffset={6}>
            <div className="px-2 py-1.5 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Выбор модели агента</div>
            <DropdownMenuSeparator className="my-1" />
            {(Object.entries(MODELS) as [ModelKey, ModelDef][]).map(([key, m]) => (
              <button
                key={key}
                onClick={() => { onModelChange?.(key); setModelOpen(false); }}
                className={cn(
                  "w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-colors",
                  model === key ? "bg-gray-50" : "hover:bg-gray-50"
                )}
              >
                <div className={cn(
                  "w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5",
                  key === "mini"     ? "bg-amber-100" :
                  key === "standard" ? "bg-blue-100" :
                  key === "sonnet"   ? "bg-violet-100" : "bg-rose-100"
                )}>
                  <span className={m.iconColor}>{m.icon}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-semibold text-gray-800">{m.label}</span>
                    <span className="text-[10px] text-gray-400 font-normal">{m.sublabel}</span>
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">{m.model}</div>
                  <div className="text-[10px] text-gray-400 mt-1">{m.desc}</div>
                  <div className="flex items-center gap-2 mt-1.5">
                    <span className={cn(
                      "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium",
                      key === "mini"     ? "bg-amber-50 text-amber-700" :
                      key === "standard" ? "bg-blue-50 text-blue-700" :
                      key === "sonnet"   ? "bg-violet-50 text-violet-700" : "bg-rose-50 text-rose-700"
                    )}>{m.pricePerTask} / запрос</span>
                    <span className="text-[10px] text-gray-400">{m.budget}</span>
                  </div>
                </div>
                <div className="shrink-0 mt-1">
                  {model === key
                    ? <Check size={14} className="text-indigo-500" />
                    : <div className="w-3.5 h-3.5" />
                  }
                </div>
              </button>
            ))}
            <DropdownMenuSeparator className="my-1" />
            <div className="px-3 py-1.5 text-[10px] text-gray-400">
              Текущий выбор: <span className="font-medium text-gray-600">{current.model}</span> · {current.speed}
            </div>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Status */}
        <div className={cn(
          "flex items-center gap-1.5",
          status === "needs_review" && "bg-yellow-50 border border-yellow-200 rounded-full px-2 py-0.5"
        )}>
          {status === "needs_review" ? (
            <AlertTriangle size={11} className="text-yellow-500 shrink-0" />
          ) : (
            <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", STATUS_COLORS[status])} />
          )}
          <span className={cn(
            "text-xs hidden sm:block",
            status === "needs_review" ? "text-yellow-700 font-medium" : "text-gray-500"
          )}>{STATUS_LABELS[status]}</span>
        </div>


        {/* Real agent stop button — shown when real API agent is running */}
        {isRunning && onStop && (
          <button
            onClick={onStop}
            className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-red-500 text-white text-xs font-semibold hover:bg-red-600 transition-colors shadow-sm"
            title="Остановить задачу"
          >
            <Square size={9} fill="currentColor" />
            Стоп
          </button>
        )}

        {/* Takeover button — shown when running */}
        {(isRunning || isTakeover) && (
          isTakeover ? (
            <button
              onClick={onTakeoverDeactivate}
              className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-amber-100 border border-amber-300 text-amber-700 text-xs font-medium hover:bg-amber-200 transition-colors"
            >
              <Terminal size={10} />
              Управление активно
            </button>
          ) : (
            <button
              onClick={onTakeoverActivate}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 text-xs font-medium hover:bg-gray-50 hover:border-gray-300 transition-colors"
              title="Взять управление — приостановить агента и вводить команды вручную"
            >
              <Terminal size={10} />
              Взять управление
            </button>
          )
        )}

        {/* Cmd+K shortcut hint */}
        {onCommandPalette && (
          <button
            onClick={onCommandPalette}
            className="hidden md:flex items-center gap-1 px-1.5 py-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title="Палитра команд (⌘K)"
          >
            <Keyboard size={13} />
          </button>
        )}

        {/* Panel toggle */}
        <button
          onClick={onToggleRightPanel}
          className={cn(
            "p-1.5 rounded-md transition-colors",
            rightPanelOpen
              ? "bg-indigo-50 text-indigo-600"
              : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
          )}
          title="Детали выполнения"
        >
          <PanelRight size={15} />
        </button>

        {/* More menu */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors">
              <MoreHorizontal size={15} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52 text-xs">
            <DropdownMenuItem className="text-xs" onClick={() => toast.info("Скоро")}>Переименовать</DropdownMenuItem>
            <DropdownMenuItem className="text-xs" onClick={() => toast.info("Скоро")}>Поделиться</DropdownMenuItem>
            <DropdownMenuItem className="text-xs" onClick={() => { exportChatMarkdown(chatTitle, projectName); toast.success("Чат экспортирован в Markdown"); }}>Экспорт в Markdown</DropdownMenuItem>

          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
