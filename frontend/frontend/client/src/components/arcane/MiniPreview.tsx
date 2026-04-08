// MiniPreview — Manus-style task progress chip above composer
// Shows: [mini-screenshot] [green check / blue pulse] [step text] [X/N counter] [expand arrow]
import { useState } from "react";
import { cn } from "@/lib/utils";
import { CheckCircle2, ChevronUp, ChevronDown, Loader2, Circle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface MiniPreviewProps {
  currentTool?: string;
  isRunning: boolean;
  planTitle?: string;
  planProgress?: string;
  steps?: { title: string; status: string; tool?: string }[];
  completedCount?: number;
  totalCount?: number;
  onClick?: () => void;
  screenshotUrl?: string;
  plan?: string[];
}

const TOOL_LABELS: Record<string, string> = {
  browser_navigate: "Открывает страницу",
  browser_click: "Нажимает элемент",
  browser_input: "Вводит текст",
  browser_scroll: "Прокручивает страницу",
  browser_view: "Просматривает страницу",
  browser_find_keyword: "Ищет на странице",
  browser_save_image: "Сохраняет изображение",
  file_write: "Записывает файл",
  file_read: "Читает файл",
  file_edit: "Редактирует файл",
  shell_exec: "Выполняет команду",
  search: "Ищет в интернете",
  message: "Отправляет результат",
};

function getStepLabel(tool?: string, title?: string): string {
  if (tool && TOOL_LABELS[tool]) return TOOL_LABELS[tool];
  if (title) return title;
  return "Выполняет задачу";
}

export function MiniPreview({
  currentTool,
  isRunning,
  planTitle,
  steps = [],
  completedCount = 0,
  totalCount = 0,
  onClick,
  screenshotUrl,
  plan = [],
}: MiniPreviewProps) {
  const [expanded, setExpanded] = useState(false);

  const lastStep = steps.length > 0 ? steps[steps.length - 1] : null;
  const displayText = planTitle || getStepLabel(currentTool || lastStep?.tool, lastStep?.title);
  const allDone = !isRunning && completedCount > 0 && completedCount >= totalCount;
  const counter = totalCount > 0 ? `${completedCount} / ${totalCount}` : undefined;

  return (
    <div className="mx-2 mb-2">
      {/* Main chip — Manus style */}
      <div
        className={cn(
          "flex items-center gap-3 px-3 py-2 cursor-pointer transition-all rounded-xl",
          "bg-white dark:bg-[#1a1d2e] border border-gray-200 dark:border-[#2a2d3a]",
          "hover:shadow-sm"
        )}
        onClick={() => setExpanded(v => !v)}
      >
        {/* Mini screenshot thumbnail */}
        {screenshotUrl ? (
          <div className="w-12 h-8 rounded-md overflow-hidden shrink-0 border border-gray-100 dark:border-gray-700 bg-gray-50">
            <img src={screenshotUrl} alt="" className="w-full h-full object-cover" />
          </div>
        ) : (
          <div className="w-12 h-8 rounded-md shrink-0 border border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 flex items-center justify-center">
            <div className="w-6 h-4 rounded-sm bg-gray-200 dark:bg-gray-700" />
          </div>
        )}

        {/* Status icon */}
        {allDone ? (
          <CheckCircle2 size={16} className="text-green-500 shrink-0" />
        ) : (
          <Loader2 size={16} className="text-blue-500 animate-spin shrink-0" />
        )}

        {/* Step text */}
        <span className="flex-1 text-sm text-gray-700 dark:text-gray-300 truncate">
          {displayText}
        </span>

        {/* Counter */}
        {counter && (
          <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0 tabular-nums">
            {counter}
          </span>
        )}

        {/* Expand arrow */}
        {expanded ? (
          <ChevronDown size={14} className="text-gray-400 shrink-0" />
        ) : (
          <ChevronUp size={14} className="text-gray-400 shrink-0" />
        )}
      </div>

      {/* Expanded plan list — Manus style */}
      <AnimatePresence initial={false}>
        {expanded && plan.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-1 bg-white dark:bg-[#1a1d2e] border border-gray-200 dark:border-[#2a2d3a] rounded-xl overflow-hidden">
              <div className="max-h-[200px] overflow-y-auto py-2">
                {plan.map((item, i) => {
                  const done = i < completedCount;
                  const running = i === completedCount && isRunning;
                  return (
                    <div key={i} className="flex items-center gap-2.5 px-4 py-1.5">
                      {done ? (
                        <CheckCircle2 size={13} className="text-green-500 shrink-0" />
                      ) : running ? (
                        <Loader2 size={13} className="text-blue-500 animate-spin shrink-0" />
                      ) : (
                        <Circle size={13} className="text-gray-300 dark:text-gray-600 shrink-0" />
                      )}
                      <span className={cn(
                        "text-xs truncate",
                        done ? "text-gray-400 line-through" : running ? "text-gray-700 dark:text-gray-200 font-medium" : "text-gray-400"
                      )}>
                        {item}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
