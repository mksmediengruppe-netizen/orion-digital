// Design: "Warm Intelligence"
// Session Insights — execution stats, token usage, speed metrics, confidence levels (like Devin)

import { cn } from "@/lib/utils";
import { motion } from "framer-motion";
import {
  Zap, Clock, DollarSign, Brain, TrendingUp, Activity,
  CheckCircle2, AlertTriangle, BarChart2, Cpu
} from "lucide-react";

interface InsightMetric {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "stable";
  color?: string;
}

const METRICS: InsightMetric[] = [
  { label: "Токены использовано", value: "18 420", sub: "из 128 000", color: "text-indigo-600" },
  { label: "Скорость", value: "42 tok/s", sub: "выше среднего", trend: "up", color: "text-green-600" },
  { label: "Итераций агента", value: "4", sub: "из ~6 ожидаемых", color: "text-gray-700" },
  { label: "Время выполнения", value: "4:12", sub: "активно", color: "text-blue-600" },
];

const TOOL_USAGE = [
  { tool: "SSH / Terminal", calls: 8, avgMs: 2100, color: "bg-green-500" },
  { tool: "Browser", calls: 5, avgMs: 3200, color: "bg-blue-500" },
  { tool: "Search", calls: 3, avgMs: 800, color: "bg-amber-500" },
  { tool: "File I/O", calls: 2, avgMs: 400, color: "bg-purple-500" },
];

const CONFIDENCE_STEPS = [
  { step: "Проверка сервера", confidence: 97, status: "done" as const },
  { step: "Установка зависимостей", confidence: 94, status: "done" as const },
  { step: "Загрузка Bitrix", confidence: 91, status: "done" as const },
  { step: "Настройка БД", confidence: 78, status: "running" as const },
  { step: "Проверка SSL", confidence: 85, status: "pending" as const },
];

const CONTEXT_USED = 18420;
const CONTEXT_TOTAL = 128000;
const CONTEXT_PCT = (CONTEXT_USED / CONTEXT_TOTAL) * 100;

export function SessionInsightsTab() {
  return (
    <div className="p-4 space-y-4 overflow-y-auto">

      {/* Key metrics grid */}
      <div className="grid grid-cols-2 gap-2">
        {METRICS.map((m, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className="rounded-xl border border-gray-100 bg-white p-3 space-y-0.5"
          >
            <div className={cn("text-lg font-bold tabular-nums", m.color)}>{m.value}</div>
            <div className="text-[11px] font-medium text-gray-600">{m.label}</div>
            {m.sub && (
              <div className={cn(
                "text-[10px]",
                m.trend === "up" ? "text-green-500" : m.trend === "down" ? "text-red-400" : "text-gray-400"
              )}>
                {m.trend === "up" && "↑ "}
                {m.trend === "down" && "↓ "}
                {m.sub}
              </div>
            )}
          </motion.div>
        ))}
      </div>

      {/* Context window usage */}
      <div className="rounded-xl border border-gray-100 bg-white p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Brain size={13} className="text-indigo-500" />
            <span className="text-xs font-semibold text-gray-700">Контекстное окно</span>
          </div>
          <span className="text-xs font-mono text-gray-500">{Math.round(CONTEXT_PCT)}%</span>
        </div>
        <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
          <motion.div
            className={cn(
              "h-2 rounded-full",
              CONTEXT_PCT > 80 ? "bg-red-400" : CONTEXT_PCT > 60 ? "bg-amber-400" : "bg-indigo-400"
            )}
            initial={{ width: 0 }}
            animate={{ width: `${CONTEXT_PCT}%` }}
            transition={{ duration: 0.6, ease: "easeOut" }}
          />
        </div>
        <div className="flex items-center justify-between text-[10px] text-gray-400">
          <span>{CONTEXT_USED.toLocaleString()} токенов использовано</span>
          <span>{(CONTEXT_TOTAL - CONTEXT_USED).toLocaleString()} осталось</span>
        </div>
        {CONTEXT_PCT > 70 && (
          <div className="flex items-center gap-1.5 text-[11px] text-amber-600 bg-amber-50 rounded-lg px-2 py-1.5">
            <AlertTriangle size={11} />
            Контекст заполнен на {Math.round(CONTEXT_PCT)}%. Рекомендуется сжатие.
          </div>
        )}
      </div>

      {/* Confidence per step */}
      <div className="rounded-xl border border-gray-100 bg-white p-3 space-y-2">
        <div className="flex items-center gap-1.5 mb-1">
          <Activity size={13} className="text-purple-500" />
          <span className="text-xs font-semibold text-gray-700">Уверенность агента</span>
        </div>
        <div className="space-y-2">
          {CONFIDENCE_STEPS.map((s, i) => (
            <div key={i} className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  {s.status === "done" && <CheckCircle2 size={11} className="text-green-500" />}
                  {s.status === "running" && <span className="w-2.5 h-2.5 rounded-full bg-indigo-500 animate-pulse block" />}
                  {s.status === "pending" && <span className="w-2.5 h-2.5 rounded-full bg-gray-200 block" />}
                  <span className={cn(
                    "text-xs",
                    s.status === "done" ? "text-gray-400 line-through" :
                    s.status === "running" ? "text-indigo-800 font-medium" : "text-gray-500"
                  )}>{s.step}</span>
                </div>
                <span className={cn(
                  "text-[11px] font-mono font-semibold",
                  s.confidence >= 90 ? "text-green-600" :
                  s.confidence >= 75 ? "text-amber-600" : "text-red-500"
                )}>{s.confidence}%</span>
              </div>
              <div className="w-full bg-gray-100 rounded-full h-1 overflow-hidden">
                <motion.div
                  className={cn(
                    "h-1 rounded-full",
                    s.confidence >= 90 ? "bg-green-400" :
                    s.confidence >= 75 ? "bg-amber-400" : "bg-red-400"
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: s.status !== "pending" ? `${s.confidence}%` : "0%" }}
                  transition={{ duration: 0.5, delay: i * 0.08 }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tool usage breakdown */}
      <div className="rounded-xl border border-gray-100 bg-white p-3 space-y-2">
        <div className="flex items-center gap-1.5 mb-1">
          <BarChart2 size={13} className="text-blue-500" />
          <span className="text-xs font-semibold text-gray-700">Использование инструментов</span>
        </div>
        <div className="space-y-2">
          {TOOL_USAGE.map((t, i) => {
            const maxCalls = Math.max(...TOOL_USAGE.map(x => x.calls));
            return (
              <div key={i} className="flex items-center gap-2">
                <span className="text-[11px] text-gray-600 w-28 shrink-0">{t.tool}</span>
                <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                  <motion.div
                    className={cn("h-1.5 rounded-full", t.color)}
                    initial={{ width: 0 }}
                    animate={{ width: `${(t.calls / maxCalls) * 100}%` }}
                    transition={{ duration: 0.5, delay: i * 0.07 }}
                  />
                </div>
                <span className="text-[10px] font-mono text-gray-400 w-12 text-right shrink-0">
                  {t.calls}x · {(t.avgMs / 1000).toFixed(1)}s
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Cost breakdown */}
      <div className="rounded-xl border border-gray-100 bg-white p-3">
        <div className="flex items-center gap-1.5 mb-2">
          <DollarSign size={13} className="text-green-500" />
          <span className="text-xs font-semibold text-gray-700">Стоимость сессии</span>
        </div>
        <div className="space-y-1.5">
          {[
            { label: "Входные токены (18 420)", cost: "$0.55" },
            { label: "Выходные токены (3 210)", cost: "$0.48" },
            { label: "Инструменты (18 вызовов)", cost: "$0.21" },
          ].map((item, i) => (
            <div key={i} className="flex items-center justify-between text-xs">
              <span className="text-gray-500">{item.label}</span>
              <span className="font-mono text-gray-700">{item.cost}</span>
            </div>
          ))}
          <div className="border-t border-gray-100 pt-1.5 flex items-center justify-between text-xs font-semibold">
            <span className="text-gray-700">Итого</span>
            <span className="text-gray-900 font-mono">$1.24</span>
          </div>
        </div>
      </div>
    </div>
  );
}
