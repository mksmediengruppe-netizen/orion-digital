// Manus-style TaskProgress — inline card in chat showing plan phases
// Green checkmark = completed, Blue pulsing dot = active, Grey clock = pending

import { useState } from "react";
import { CheckCircle2, Clock, ChevronRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

interface TaskProgressProps {
  plan: string[];
  completedCount: number;
  activeIndex?: number;
  elapsed?: number;
  className?: string;
}

export function TaskProgress({ plan, completedCount, activeIndex, elapsed, className }: TaskProgressProps) {
  const [expanded, setExpanded] = useState(true);

  if (plan.length === 0) return null;

  // Active phase is either explicitly set or the first incomplete phase
  const currentPhase = activeIndex !== undefined && activeIndex >= 0 ? activeIndex : completedCount;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "mt-3 rounded-xl border border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-[#13151f] overflow-hidden shadow-sm",
        className
      )}
    >
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-[#1a1d2e] transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm text-gray-800 dark:text-gray-200">
            Прогресс задачи
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 font-mono">
            {completedCount} / {plan.length}
          </span>
          <motion.span
            animate={{ rotate: expanded ? 90 : 0 }}
            transition={{ duration: 0.15 }}
            className="text-gray-400"
          >
            <ChevronRight size={14} />
          </motion.span>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 space-y-0.5">
              {plan.map((phase, i) => {
                const isCompleted = i < completedCount;
                const isActive = i === currentPhase && !isCompleted;
                const isPending = !isCompleted && !isActive;

                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.15, delay: i * 0.03 }}
                    className={cn(
                      "flex items-start gap-3 py-2 px-2 rounded-lg transition-colors",
                      isActive && "bg-blue-50/50 dark:bg-blue-900/10"
                    )}
                  >
                    <div className="mt-0.5 shrink-0">
                      {isCompleted ? (
                        <CheckCircle2 size={16} className="text-green-500" />
                      ) : isActive ? (
                        <div className="relative flex items-center justify-center w-4 h-4">
                          <span className="absolute w-3 h-3 rounded-full bg-blue-500 animate-ping opacity-30" />
                          <span className="relative w-2.5 h-2.5 rounded-full bg-blue-500" />
                        </div>
                      ) : (
                        <Clock size={16} className="text-gray-300 dark:text-gray-600" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <span className={cn(
                        "text-sm leading-snug",
                        isCompleted && "text-gray-500 dark:text-gray-400",
                        isActive && "text-gray-800 dark:text-gray-200 font-medium",
                        isPending && "text-gray-400 dark:text-gray-600"
                      )}>
                        {phase}
                      </span>
                      {isActive && elapsed !== undefined && elapsed > 0 && (
                        <div className="text-[10px] text-gray-400 mt-0.5 font-mono">
                          {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}  ·  Думает
                        </div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
