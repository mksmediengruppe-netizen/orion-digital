// ORION SSEReconnectingBanner — "Warm Intelligence" design
// Shows a persistent banner when the real-time SSE connection is lost.
// States: reconnecting (yellow), failed (red), offline (gray)

import { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import { WifiOff, Loader2, RefreshCw, X, Wifi, AlertTriangle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export type SSEConnectionState = "connected" | "reconnecting" | "failed" | "offline";

interface SSEReconnectingBannerProps {
  state: SSEConnectionState;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export function SSEReconnectingBanner({ state, onRetry, onDismiss, className }: SSEReconnectingBannerProps) {
  const [attempt, setAttempt] = useState(1);
  const [countdown, setCountdown] = useState(3);

  useEffect(() => {
    if (state !== "reconnecting") return;
    const interval = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) {
          setAttempt(a => a + 1);
          return 3;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [state]);

  useEffect(() => {
    if (state === "connected") {
      setAttempt(1);
      setCountdown(3);
    }
  }, [state]);

  if (state === "connected") return null;

  const config = {
    reconnecting: {
      bg: "bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800",
      text: "text-amber-800 dark:text-amber-200",
      icon: <Loader2 size={14} className="text-amber-600 animate-spin shrink-0" />,
      title: "Переподключение...",
      subtitle: `Попытка ${attempt} · следующая через ${countdown} сек`,
    },
    failed: {
      bg: "bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800",
      text: "text-red-800 dark:text-red-200",
      icon: <AlertTriangle size={14} className="text-red-600 shrink-0" />,
      title: "Соединение потеряно",
      subtitle: "Не удалось восстановить соединение с сервером",
    },
    offline: {
      bg: "bg-gray-100 dark:bg-gray-800/60 border-gray-200 dark:border-gray-700",
      text: "text-gray-700 dark:text-gray-300",
      icon: <WifiOff size={14} className="text-gray-500 shrink-0" />,
      title: "Нет подключения к интернету",
      subtitle: "Обновления в реальном времени недоступны",
    },
  }[state];

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.2, ease: "easeInOut" }}
      className={cn(
        "border-b overflow-hidden shrink-0",
        config.bg,
        className
      )}
    >
      <div className={cn("flex items-center gap-2.5 px-4 py-2 text-xs", config.text)}>
        {config.icon}
        <div className="flex-1 min-w-0">
          <span className="font-semibold">{config.title}</span>
          <span className="ml-1.5 opacity-70">{config.subtitle}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {(state === "failed" || state === "offline") && onRetry && (
            <button
              onClick={onRetry}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors",
                state === "failed"
                  ? "bg-red-100 dark:bg-red-900/50 hover:bg-red-200 dark:hover:bg-red-900 text-red-700 dark:text-red-300"
                  : "bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-300"
              )}
            >
              <RefreshCw size={11} />
              Повторить
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              className={cn("p-1 rounded hover:bg-black/5 dark:hover:bg-white/10 transition-colors", config.text)}
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ─── Demo hook (backward compat) ─────────────────────────────────────────────
// Used in Home.tsx via useSSEConnectionDemo.
// In production, swap this import for useSSEConnectionSafe from hooks/useSSEConnection.

export function useSSEConnectionDemo() {
  const [sseState, setSSEState] = useState<SSEConnectionState>("connected");
  const [showBanner, setShowBanner] = useState(false);

  // ── Online / Offline detection (real browser events) ──────────────────────
  useEffect(() => {
    const handleOffline = () => {
      setSSEState("offline");
      setShowBanner(true);
    };
    const handleOnline = () => {
      // Simulate brief reconnecting phase then restore
      setSSEState("reconnecting");
      setShowBanner(true);
      const t = setTimeout(() => {
        setSSEState("connected");
        setShowBanner(false);
      }, 3000);
      return () => clearTimeout(t);
    };
    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);
    return () => {
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
    };
  }, []);

  // ── Manual simulation triggers (for demo ⋯ menu) ──────────────────────────
  const simulateDisconnect = useCallback(() => {
    setSSEState("reconnecting");
    setShowBanner(true);
    const t = setTimeout(() => {
      setSSEState("connected");
      setShowBanner(false);
    }, 8000);
    return () => clearTimeout(t);
  }, []);

  const simulateFailed = useCallback(() => {
    setSSEState("failed");
    setShowBanner(true);
  }, []);

  const simulateOffline = useCallback(() => {
    setSSEState("offline");
    setShowBanner(true);
  }, []);

  const retry = useCallback(() => {
    setSSEState("reconnecting");
    const t = setTimeout(() => {
      setSSEState("connected");
      setShowBanner(false);
    }, 3000);
    return () => clearTimeout(t);
  }, []);

  return { sseState, showBanner, simulateDisconnect, simulateFailed, simulateOffline, retry, setShowBanner };
}
