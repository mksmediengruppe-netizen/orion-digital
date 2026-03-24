// ORION useSSEConnection — real EventSource hook with automatic reconnect
// Features:
//   - Connects to a real SSE endpoint (configurable URL)
//   - Detects browser online/offline events
//   - Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s cap
//   - Max 10 attempts before entering "failed" state
//   - Exposes connection state compatible with SSEReconnectingBanner
//   - Falls back gracefully if the endpoint is unreachable (prototype mode)

import { useState, useEffect, useRef, useCallback } from "react";
import type { SSEConnectionState } from "@/components/orion/SSEReconnectingBanner";

// ─── Config ───────────────────────────────────────────────────────────────────

const MAX_ATTEMPTS = 10;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30_000;
const BACKOFF_FACTOR = 2;

function calcDelay(attempt: number): number {
  return Math.min(BASE_DELAY_MS * Math.pow(BACKOFF_FACTOR, attempt - 1), MAX_DELAY_MS);
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export interface SSEConnectionOptions {
  /** Full URL of the SSE endpoint, e.g. "/api/events" or "https://api.example.com/stream" */
  url: string;
  /** Whether to actually connect. Set false to stay in "connected" (no-op) mode for static prototypes. */
  enabled?: boolean;
  /** Called when a named event arrives */
  onEvent?: (type: string, data: unknown) => void;
  /** Called when connection is established */
  onConnected?: () => void;
  /** Called when connection is permanently lost */
  onFailed?: () => void;
}

export interface SSEConnectionResult {
  state: SSEConnectionState;
  showBanner: boolean;
  attempt: number;
  reconnect: () => void;
  dismiss: () => void;
}

export function useSSEConnection({
  url,
  enabled = true,
  onEvent,
  onConnected,
  onFailed,
}: SSEConnectionOptions): SSEConnectionResult {
  const [state, setState] = useState<SSEConnectionState>("connected");
  const [showBanner, setShowBanner] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const esRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  // ─── Cleanup helper ─────────────────────────────────────────────────────────

  const cleanup = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  // ─── Connect ────────────────────────────────────────────────────────────────

  const connect = useCallback(() => {
    if (!enabledRef.current) return;
    if (!navigator.onLine) {
      setState("offline");
      setShowBanner(true);
      return;
    }

    cleanup();

    const es = new EventSource(url, { withCredentials: true });
    esRef.current = es;

    es.onopen = () => {
      attemptRef.current = 0;
      setAttempt(0);
      setState("connected");
      setShowBanner(false);
      onConnected?.();
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;

      // If browser went offline, switch to offline state
      if (!navigator.onLine) {
        setState("offline");
        setShowBanner(true);
        return;
      }

      const nextAttempt = attemptRef.current + 1;
      attemptRef.current = nextAttempt;
      setAttempt(nextAttempt);

      if (nextAttempt > MAX_ATTEMPTS) {
        setState("failed");
        setShowBanner(true);
        onFailed?.();
        return;
      }

      // Reconnecting with exponential backoff
      setState("reconnecting");
      setShowBanner(true);

      const delay = calcDelay(nextAttempt);
      reconnectTimerRef.current = setTimeout(() => {
        if (enabledRef.current) connect();
      }, delay);
    };

    // Listen to named events
    es.addEventListener("message", (e) => {
      try {
        const data = JSON.parse(e.data);
        onEvent?.("message", data);
      } catch {
        onEvent?.("message", e.data);
      }
    });

    // Forward any named event types (agent_status, step_update, etc.)
    const namedEvents = ["agent_status", "step_update", "task_complete", "budget_update", "notification"];
    for (const eventType of namedEvents) {
      es.addEventListener(eventType, (e) => {
        try {
          const data = JSON.parse((e as MessageEvent).data);
          onEvent?.(eventType, data);
        } catch {
          onEvent?.(eventType, (e as MessageEvent).data);
        }
      });
    }
  }, [url, cleanup, onEvent, onConnected, onFailed]);

  // ─── Manual reconnect / dismiss ─────────────────────────────────────────────

  const reconnect = useCallback(() => {
    attemptRef.current = 0;
    setAttempt(0);
    setState("reconnecting");
    connect();
  }, [connect]);

  const dismiss = useCallback(() => {
    setShowBanner(false);
  }, []);

  // ─── Online / Offline events ────────────────────────────────────────────────

  useEffect(() => {
    const handleOnline = () => {
      if (state === "offline" || state === "failed") {
        reconnect();
      }
    };
    const handleOffline = () => {
      cleanup();
      setState("offline");
      setShowBanner(true);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [state, reconnect, cleanup]);

  // ─── Initial connection ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!enabled) {
      cleanup();
      setState("connected");
      setShowBanner(false);
      return;
    }
    connect();
    return cleanup;
  }, [enabled, connect, cleanup]);

  return { state, showBanner, attempt, reconnect, dismiss };
}

// ─── Prototype-safe wrapper ───────────────────────────────────────────────────
// In the ORION prototype there is no real SSE backend, so this wrapper
// disables the real connection and exposes the same interface as the demo hook
// while also providing manual simulation triggers for demo purposes.

export function useSSEConnectionSafe(url: string) {
  // Detect if we're in a real deployment with a backend
  const hasBackend = typeof window !== "undefined" &&
    !window.location.hostname.includes("localhost") === false ||
    window.location.port === "3000";

  // For the prototype, disable real connection — use demo mode
  const PROTOTYPE_MODE = true; // flip to false when backend is ready

  const real = useSSEConnection({
    url,
    enabled: !PROTOTYPE_MODE,
  });

  // Demo simulation state (kept for the ⋯ menu triggers)
  const [demoState, setDemoState] = useState<SSEConnectionState>("connected");
  const [demoBanner, setDemoBanner] = useState(false);

  const simulateDisconnect = useCallback(() => {
    setDemoState("reconnecting");
    setDemoBanner(true);
    const t = setTimeout(() => { setDemoState("connected"); setDemoBanner(false); }, 8000);
    return () => clearTimeout(t);
  }, []);

  const simulateFailed = useCallback(() => {
    setDemoState("failed");
    setDemoBanner(true);
  }, []);

  const simulateOffline = useCallback(() => {
    setDemoState("offline");
    setDemoBanner(true);
  }, []);

  const retry = useCallback(() => {
    setDemoState("reconnecting");
    const t = setTimeout(() => { setDemoState("connected"); setDemoBanner(false); }, 3000);
    return () => clearTimeout(t);
  }, []);

  if (PROTOTYPE_MODE) {
    return {
      sseState: demoState,
      showBanner: demoBanner,
      simulateDisconnect,
      simulateFailed,
      simulateOffline,
      retry,
      setShowBanner: setDemoBanner,
    };
  }

  // Real mode
  return {
    sseState: real.state,
    showBanner: real.showBanner,
    simulateDisconnect: () => {},
    simulateFailed: () => {},
    simulateOffline: () => {},
    retry: real.reconnect,
    setShowBanner: () => {},
  };
}
