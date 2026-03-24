// Design: "Warm Intelligence"
// Takeover mode — user can interrupt agent and type commands directly (like Devin)

import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Terminal, X, Send, AlertTriangle, ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";

interface TakeoverModeProps {
  isActive: boolean;
  onActivate: () => void;
  onDeactivate: () => void;
  onSendCommand: (cmd: string) => void;
}

const QUICK_COMMANDS = [
  "ls -la /var/www/",
  "systemctl status nginx",
  "tail -f /var/log/nginx/error.log",
  "php -v && mysql --version",
];

export function TakeoverBanner({ isActive, onActivate, onDeactivate }: {
  isActive: boolean;
  onActivate: () => void;
  onDeactivate: () => void;
}) {
  if (isActive) {
    return (
      <motion.div
        initial={{ height: 0, opacity: 0 }}
        animate={{ height: "auto", opacity: 1 }}
        exit={{ height: 0, opacity: 0 }}
        className="border-b border-amber-200 bg-amber-50 px-4 py-2 flex items-center gap-2 shrink-0"
      >
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
          <Terminal size={13} className="text-amber-600" />
          <span className="text-xs font-semibold text-amber-800">Режим управления активен</span>
        </div>
        <span className="text-xs text-amber-600 flex-1">Агент приостановлен. Вы управляете напрямую.</span>
        <button
          onClick={onDeactivate}
          className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-amber-200 text-amber-800 text-xs font-medium hover:bg-amber-300 transition-colors"
        >
          <X size={10} />
          Вернуть агенту
        </button>
      </motion.div>
    );
  }

  return null;
}

export function TakeoverPanel({ isActive, onSendCommand }: {
  isActive: boolean;
  onSendCommand: (cmd: string) => void;
}) {
  const [value, setValue] = useState("");
  const [history, setHistory] = useState<{ cmd: string; output: string }[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const outputRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isActive) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isActive]);

  useEffect(() => {
    outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: "smooth" });
  }, [history]);

  const handleSend = () => {
    const cmd = value.trim();
    if (!cmd) return;
    const output = simulateOutput(cmd);
    setHistory(prev => [...prev, { cmd, output }]);
    onSendCommand(cmd);
    setValue("");
    setHistoryIndex(-1);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleSend();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const cmds = history.map(h => h.cmd);
      const newIdx = Math.min(historyIndex + 1, cmds.length - 1);
      setHistoryIndex(newIdx);
      setValue(cmds[cmds.length - 1 - newIdx] ?? "");
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      const newIdx = Math.max(historyIndex - 1, -1);
      setHistoryIndex(newIdx);
      setValue(newIdx === -1 ? "" : history[history.length - 1 - newIdx]?.cmd ?? "");
    }
  };

  if (!isActive) return null;

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: 220, opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.2 }}
      className="border-t border-amber-200 bg-gray-900 flex flex-col overflow-hidden shrink-0"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 border-b border-gray-700 shrink-0">
        <div className="flex gap-1">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500" />
          <div className="w-2.5 h-2.5 rounded-full bg-amber-500" />
          <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
        </div>
        <span className="text-[11px] text-gray-400 font-mono flex-1">takeover@185.22.xx.xx</span>
        <span className="text-[10px] text-amber-400 font-medium">УПРАВЛЕНИЕ</span>
      </div>

      {/* Output */}
      <div
        ref={outputRef}
        className="flex-1 overflow-y-auto p-3 font-mono text-[11px] space-y-2"
      >
        {history.length === 0 && (
          <div className="text-gray-500">
            <div># Режим управления. Вы управляете сервером напрямую.</div>
            <div className="mt-1"># Агент приостановлен и ждёт вашей команды.</div>
          </div>
        )}
        {history.map((h, i) => (
          <div key={i}>
            <div className="text-green-400">$ {h.cmd}</div>
            <div className="text-gray-300 mt-0.5 whitespace-pre-wrap">{h.output}</div>
          </div>
        ))}
      </div>

      {/* Quick commands */}
      <div className="flex items-center gap-1.5 px-3 py-1.5 border-t border-gray-700 overflow-x-auto shrink-0">
        {QUICK_COMMANDS.map((cmd, i) => (
          <button
            key={i}
            onClick={() => { setValue(cmd); inputRef.current?.focus(); }}
            className="shrink-0 px-2 py-0.5 rounded bg-gray-700 text-gray-300 text-[10px] font-mono hover:bg-gray-600 transition-colors whitespace-nowrap"
          >
            {cmd}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-gray-700 shrink-0">
        <span className="text-green-400 font-mono text-[12px] shrink-0">$</span>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Введите команду..."
          className="flex-1 bg-transparent text-green-300 font-mono text-[12px] outline-none placeholder:text-gray-600"
        />
        <button
          onClick={handleSend}
          disabled={!value.trim()}
          className="p-1.5 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <Send size={11} />
        </button>
      </div>
    </motion.div>
  );
}

// ─── Takeover Button (shown in ChatHeader during execution) ───────────────────

export function TakeoverButton({ isRunning, isTakeover, onActivate, onDeactivate }: {
  isRunning: boolean;
  isTakeover: boolean;
  onActivate: () => void;
  onDeactivate: () => void;
}) {
  if (!isRunning && !isTakeover) return null;

  if (isTakeover) {
    return (
      <button
        onClick={onDeactivate}
        className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-amber-100 border border-amber-300 text-amber-700 text-xs font-medium hover:bg-amber-200 transition-colors"
      >
        <Terminal size={10} />
        Управление активно
      </button>
    );
  }

  return (
    <button
      onClick={onActivate}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 text-xs font-medium hover:bg-gray-50 hover:border-gray-300 transition-colors"
      title="Взять управление — приостановить агента и вводить команды вручную"
    >
      <Terminal size={10} />
      Взять управление
    </button>
  );
}

// ─── Simulate terminal output ─────────────────────────────────────────────────

function simulateOutput(cmd: string): string {
  const cmd_lower = cmd.toLowerCase();
  if (cmd_lower.includes("ls")) return "drwxr-xr-x  2 www-data www-data 4096 Mar 15 14:32 bitrix\ndrwxr-xr-x  2 www-data www-data 4096 Mar 15 14:30 public_html\n-rw-r--r--  1 www-data www-data  220 Mar 15 14:28 .env";
  if (cmd_lower.includes("nginx")) return "● nginx.service - A high performance web server\n   Loaded: loaded (/lib/systemd/system/nginx.service; enabled)\n   Active: active (running) since Mon 2024-03-15 14:32:01 UTC";
  if (cmd_lower.includes("tail")) return "[2024-03-15 14:35:01] 200 GET /bitrix/admin/ - 0.042s\n[2024-03-15 14:35:02] 200 GET /bitrix/js/main/core.js - 0.008s";
  if (cmd_lower.includes("php")) return "PHP 8.2.10 (cli) (built: Sep 28 2023)\nmysql  Ver 8.0.35 Distrib 8.0.35, for Linux (x86_64)";
  if (cmd_lower.includes("systemctl")) return "● nginx.service - active (running)";
  return `${cmd}: выполнено успешно`;
}
