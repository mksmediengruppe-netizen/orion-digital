// useLiveTimer — counts up in real time while running is true
// Returns formatted string like "0:04", "1:23", "12:05"
import { useState, useEffect, useRef } from "react";

export function useLiveTimer(running: boolean): string {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (running) {
      // Start fresh — only initialise startRef if not already running
      if (startRef.current === null) {
        startRef.current = Date.now() - elapsed * 1000;
      }
      const tick = () => {
        if (startRef.current === null) return;
        const secs = Math.floor((Date.now() - startRef.current) / 1000);
        setElapsed(secs);
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } else {
      // Pause — cancel animation frame but keep elapsed
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      startRef.current = null;
    }
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

// Reset version — also exposes a reset function
export function useLiveTimerWithReset(running: boolean): { time: string; reset: () => void } {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);
  const rafRef = useRef<number | null>(null);
  // Track previous running value to detect false→true transition
  const prevRunningRef = useRef<boolean>(false);

  const reset = () => {
    setElapsed(0);
    startRef.current = null;
    prevRunningRef.current = false;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };

  useEffect(() => {
    if (running) {
      // Only start the timer when transitioning from false → true
      // This prevents resetting the timer if running stays true between renders
      if (!prevRunningRef.current) {
        // Fresh start
        startRef.current = Date.now();
        setElapsed(0);
      }
      prevRunningRef.current = true;

      // Cancel any existing RAF before starting a new one
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }

      const tick = () => {
        if (startRef.current === null) return;
        const secs = Math.floor((Date.now() - startRef.current) / 1000);
        setElapsed(secs);
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } else {
      prevRunningRef.current = false;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      startRef.current = null;
    }
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [running]);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const time = elapsed === 0 && !running ? "" : `${mins}:${String(secs).padStart(2, "0")}`;
  return { time, reset };
}
