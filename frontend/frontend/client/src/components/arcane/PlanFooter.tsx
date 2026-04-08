// ARCANE PlanFooter — collapsible task plan above composer, Manus-style
// Shows X/N counter, chevron toggle, items with checkmarks/spinner/circles

import { useState } from "react";
import { cn } from "@/lib/utils";
import { CheckCircle2, Circle, ChevronUp, ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface PlanFooterProps {
  plan: string[];
  completedCount: number;
  activeIndex?: number; // index of currently running step
}

export function PlanFooter({ plan, completedCount, activeIndex }: PlanFooterProps) {
  const [expanded, setExpanded] = useState(false);

  if (!plan || plan.length === 0) return null;

  const allDone = completedCount >= plan.length;

  return (
    <div className="border-t border-[#E8E6E1] dark:border-[#2a2d3a] bg-[#FAFAF9] dark:bg-[#0f1117]">
      {/* Header row — always visible */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-[#F5F4F2] dark:hover:bg-[#1a1d2e] transition-colors group"
      >
        <div className="flex items-center gap-2">
          {/* Status dot */}
          {allDone ? (
            <CheckCircle2 size={13} className="text-green-500 shrink-0" />
          ) : (
            <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse shrink-0" />
          )}
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
            {allDone ? "Задача выполнена" : "Выполняется задача"}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* X / N counter */}
          <span className="text-xs font-mono text-gray-500">
            {completedCount} / {plan.length}
          </span>
          {expanded
            ? <ChevronUp size={13} className="text-gray-400 group-hover:text-gray-600 transition-colors" />
            : <ChevronDown size={13} className="text-gray-400 group-hover:text-gray-600 transition-colors" />
          }
        </div>
      </button>

      {/* Expandable plan list */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="plan-list"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <ol className="px-4 pb-3 space-y-1.5">
              {plan.map((item, i) => {
                const done = i < completedCount;
                const running = i === activeIndex && !done;
                return (
                  <li key={i} className="flex items-start gap-2.5 text-xs">
                    <span className={cn(
                      "shrink-0 mt-0.5 transition-colors",
                      done ? "text-green-500" : running ? "text-indigo-500" : "text-gray-300"
                    )}>
                      {done ? (
                        <CheckCircle2 size={13} />
                      ) : running ? (
                        <span className="block w-3 h-3 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
                      ) : (
                        <Circle size={13} />
                      )}
                    </span>
                    <span className={cn(
                      "leading-relaxed transition-colors",
                      done
                        ? "text-gray-400 line-through"
                        : running
                          ? "text-gray-900 font-medium"
                          : "text-gray-500"
                    )}>
                      {item}
                    </span>
                  </li>
                );
              })}
            </ol>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
