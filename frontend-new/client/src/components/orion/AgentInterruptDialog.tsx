// Design: "Warm Intelligence"
// Agent interruption — agent asks user for clarification mid-task (like Devin/Manus)

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Bot, MessageCircle, X, ArrowRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";

interface AgentInterruptProps {
  question: string;
  options?: string[];
  onAnswer: (answer: string) => void;
  onDismiss: () => void;
}

export function AgentInterruptDialog({ question, options, onAnswer, onDismiss }: AgentInterruptProps) {
  const [customAnswer, setCustomAnswer] = useState("");

  const handleOption = (opt: string) => {
    onAnswer(opt);
    toast.success("Ответ отправлен агенту");
  };

  const handleCustom = () => {
    if (!customAnswer.trim()) return;
    onAnswer(customAnswer.trim());
    toast.success("Ответ отправлен агенту");
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 16, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.97 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="mx-4 mb-3 rounded-2xl border border-indigo-200 bg-indigo-50 shadow-lg overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-indigo-100">
        <div className="w-7 h-7 rounded-full bg-indigo-100 border border-indigo-200 flex items-center justify-center shrink-0">
          <Bot size={13} className="text-indigo-600" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
            <span className="text-xs font-semibold text-indigo-800">Агент ждёт вашего ответа</span>
          </div>
          <div className="text-[10px] text-indigo-500 mt-0.5">Задача приостановлена</div>
        </div>
        <button
          onClick={onDismiss}
          className="p-1 rounded-lg text-indigo-400 hover:text-indigo-600 hover:bg-indigo-100 transition-colors"
        >
          <X size={13} />
        </button>
      </div>

      {/* Question */}
      <div className="px-4 py-3">
        <div className="flex items-start gap-2">
          <MessageCircle size={13} className="text-indigo-500 mt-0.5 shrink-0" />
          <p className="text-sm text-indigo-900 leading-relaxed">{question}</p>
        </div>
      </div>

      {/* Options */}
      {options && options.length > 0 && (
        <div className="px-4 pb-3 space-y-1.5">
          {options.map((opt, i) => (
            <button
              key={i}
              onClick={() => handleOption(opt)}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-xl border border-indigo-200 bg-white hover:border-indigo-400 hover:bg-indigo-50/80 text-left text-sm text-indigo-800 transition-all group"
            >
              <span className="w-5 h-5 rounded-full bg-indigo-100 flex items-center justify-center text-[10px] font-bold text-indigo-600 shrink-0">
                {String.fromCharCode(65 + i)}
              </span>
              <span className="flex-1">{opt}</span>
              <ArrowRight size={11} className="text-indigo-300 group-hover:text-indigo-500 transition-colors shrink-0" />
            </button>
          ))}
        </div>
      )}

      {/* Custom answer */}
      <div className="px-4 pb-4">
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl border border-indigo-200 bg-white focus-within:border-indigo-400 transition-colors">
          <input
            type="text"
            value={customAnswer}
            onChange={e => setCustomAnswer(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") handleCustom(); }}
            placeholder="Или введите свой ответ..."
            className="flex-1 text-sm bg-transparent outline-none text-gray-800 placeholder:text-gray-400"
          />
          <button
            onClick={handleCustom}
            disabled={!customAnswer.trim()}
            className="p-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <ArrowRight size={11} />
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Interrupt Trigger (demo) ─────────────────────────────────────────────────

export function useAgentInterrupt() {
  const [interrupt, setInterrupt] = useState<{
    question: string;
    options?: string[];
  } | null>(null);

  const triggerInterrupt = (question: string, options?: string[]) => {
    setInterrupt({ question, options });
  };

  const handleAnswer = (answer: string) => {
    setInterrupt(null);
  };

  const handleDismiss = () => {
    setInterrupt(null);
  };

  return { interrupt, triggerInterrupt, handleAnswer, handleDismiss };
}
