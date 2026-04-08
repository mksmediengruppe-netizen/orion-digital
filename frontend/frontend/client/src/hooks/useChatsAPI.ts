import { useState, useEffect, useCallback, useRef } from "react";
import api from "@/lib/api";
import type { Chat, Message, Step, StepStatus, LogEntry } from "@/lib/mockData";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ApiChat {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  total_cost?: number;
  model_used?: string;
  variant?: string;
  status?: string;
}

interface ApiMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string;
  timestamp?: string;
}

/** Real-time cost + model info per chat */
export interface ChatMeta {
  model: string;
  cost: number;
  inputTokens: number;
  outputTokens: number;
  iterationCount: number;
  /** ISO timestamp when task started */
  startedAt: string | null;
  /** Elapsed seconds (updated via timer) */
  elapsed: number;
  /** Plan steps from plan_update events */
  plan: string[];
  /** Completed plan step indices */
  planCompleted: number[];
  /** Live steps from step_update events */
  steps: Step[];
  /** Current thinking content */
  thinkingContent: string;
  /** Real-time log entries from log SSE events */
  logs: LogEntry[];
}

// Re-export LogEntry for consumers
export type { LogEntry };

function emptyMeta(): ChatMeta {
  return {
    model: "",
    cost: 0,
    inputTokens: 0,
    outputTokens: 0,
    iterationCount: 0,
    startedAt: null,
    elapsed: 0,
    plan: [],
    planCompleted: [],
    steps: [],
    thinkingContent: "",
    logs: [],
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function apiChatToUiChat(c: ApiChat): Chat {
  return {
    id: c.id,
    projectId: "default",
    title: c.title || "Новый чат",
    mode: (c.variant as "fast" | "standard" | "premium") || "premium",
    status: (c.status as Chat["status"]) || "idle",
    cost: c.total_cost || 0,
    duration: "",
    lastMessage: "",
    timestamp: c.updated_at
      ? new Date(c.updated_at).toLocaleString("ru", { hour: "2-digit", minute: "2-digit" })
      : "",
    model: c.model_used || "",
  };
}

function apiMessageToUiMessage(m: ApiMessage): Message {
  const ts = m.created_at || m.timestamp || "";
  return {
    id: m.id,
    role: m.role === "assistant" ? "agent" : m.role === "system" ? "system" : "user",
    content: m.content || "",
    timestamp: ts
      ? new Date(ts).toLocaleString("ru", { hour: "2-digit", minute: "2-digit" })
      : "",
  };
}

export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m > 0) return `${m}м ${s}с`;
  return `${s}с`;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useChatsAPI() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeChat, setActiveChat] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, Message[]>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [agentStatus, setAgentStatus] = useState<Record<string, string>>({});
  const [chatMeta, setChatMeta] = useState<Record<string, ChatMeta>>({});
  const loadedChats = useRef(new Set<string>());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isCreatingChat = useRef(false);

  // ─── Timer management ─────────────────────────────────────────────────────
  const startTimer = useCallback((chatId: string) => {
    setChatMeta((prev) => {
      const meta = prev[chatId] || emptyMeta();
      if (meta.startedAt) return prev;
      return { ...prev, [chatId]: { ...meta, startedAt: new Date().toISOString(), elapsed: 0 } };
    });
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setChatMeta((prev) => {
        const meta = prev[chatId];
        if (!meta?.startedAt) return prev;
        const elapsed = Math.floor((Date.now() - new Date(meta.startedAt).getTime()) / 1000);
        return { ...prev, [chatId]: { ...meta, elapsed } };
      });
    }, 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  // ─── Load chats list ─────────────────────────────────────────────────────
  const loadChats = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await api.chats.list();
      const uiChats = (data.chats || []).map(apiChatToUiChat);
      // Merge: preserve completed/failed status from SSE to avoid admin polling overwrite
      setChats((prev) => {
        if (prev.length === 0) return uiChats;
        const prevMap = new Map(prev.map((c) => [c.id, c]));
        return uiChats.map((c) => {
          const existing = prevMap.get(c.id);
          // Don't overwrite completed/failed status set by SSE with stale backend data
          if (existing && (existing.status === "completed" || existing.status === "failed") && c.status !== "completed" && c.status !== "failed") {
            return { ...c, status: existing.status };
          }
          return c;
        });
      });
      if (uiChats.length > 0) {
        setActiveChat((prev) => prev ?? uiChats[0].id);
      }
      return uiChats;
    } catch (err) {
      console.error("Failed to load chats:", err);
      return [];
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { loadChats(); }, [loadChats]);

  // ─── Admin polling: refresh chat list every 5s to see API-launched tasks ──
  useEffect(() => {
    // Check if user is admin by looking at role in localStorage or cookie
    const isAdmin = (() => {
      try {
        const stored = localStorage.getItem("arcane_user");
        if (stored) {
          const parsed = JSON.parse(stored);
          return parsed.role === "admin";
        }
      } catch {}
      return false;
    })();
    if (!isAdmin) return;
    const pollInterval = setInterval(() => {
      loadChats();
    }, 5000);
    return () => clearInterval(pollInterval);
  }, [loadChats]);

  
  // ─── Safety timeout: auto-reset isSending after 120s ──────────────────────
  useEffect(() => {
    if (!isSending) return;
    const timeout = setTimeout(() => {
      console.warn("Safety timeout: resetting isSending after 120s");
      setIsSending(false);
      stopTimer();
    }, 120000);
    return () => clearTimeout(timeout);
  }, [isSending, stopTimer]);

  // ─── Load messages for a chat ─────────────────────────────────────────────
  const loadMessages = useCallback(async (chatId: string) => {
    if (loadedChats.current.has(chatId)) return;
    loadedChats.current.add(chatId);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await api.chats.get(chatId);
      const chat = data.chat || data;
      const msgs: ApiMessage[] = chat.messages || [];
      setMessages((prev) => ({
        ...prev,
        [chatId]: msgs.map(apiMessageToUiMessage),
      }));
      // Restore steps from backend if available
      const savedSteps: Step[] = (chat.steps || []).map((s: any) => ({
        id: s.step_id || s.id || String(Date.now()),
        title: s.title || s.tool || "Шаг",
        status: (s.status as StepStatus) || "success",
        tool: s.tool || "",
        startTime: s.start_time ? new Date(s.start_time * 1000).toISOString() : new Date().toISOString(),
        duration: s.duration || "",
        summary: s.result || "",
        args: s.params,
        result: s.result !== undefined && s.result !== null ? (typeof s.result === 'string' ? s.result : JSON.stringify(s.result)) : undefined,
      }));
      if (savedSteps.length > 0) {
        setChatMeta((prev) => ({
          ...prev,
          [chatId]: { ...(prev[chatId] || emptyMeta()), steps: savedSteps },
        }));
        // Also attach steps to the last agent message so they show in chat
        setMessages((prev) => {
          const chatMsgs = prev[chatId] || [];
          if (chatMsgs.length === 0) return prev;
          // Find the last agent message
          const lastAgentIdx = [...chatMsgs].map((m, i) => ({ m, i })).reverse().find(({ m }) => m.role === "agent")?.i;
          if (lastAgentIdx === undefined) return prev;
          const updated = chatMsgs.map((m, i) =>
            i === lastAgentIdx ? { ...m, steps: savedSteps } : m
          );
          return { ...prev, [chatId]: updated };
        });
      }
    } catch (err) {
      console.error("Failed to load messages:", err);
      loadedChats.current.delete(chatId);
    }
  }, []);

  // ─── Select chat ──────────────────────────────────────────────────────────
  // ─── SSE subscription for admin viewing running tasks ──────────────────
  const sseRef = useRef<EventSource | null>(null);
  
  const subscribeToRunningChat = useCallback((chatId: string) => {
    // Close previous SSE connection
    if (sseRef.current) {
      sseRef.current.close();
      sseRef.current = null;
    }
    // Only subscribe if not currently sending (i.e., admin viewing someone else's task)
    if (isSending) return;
    
    const es = api.sse.subscribe(chatId);
    sseRef.current = es;
    
    const agentMsgId = `live_${Date.now()}`;
    let fullContent = "";
    let hasAgentMsg = false;
    
    es.addEventListener("agent_status", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const status = data.status || "";
        if (status === "thinking" || status === "working" || status === "coding" || status === "browsing") {
          setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
          setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, status: "executing" } : c)));
        } else if (status === "idle" || status === "completed") {
          setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
          setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c)));
          es.close();
          sseRef.current = null;
          // Reload messages to get final result
          loadedChats.current.delete(chatId);
          loadMessages(chatId);
        }
      } catch {}
    });
    
    es.addEventListener("step", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const step = {
          id: data.step_id || String(Date.now()),
          title: data.title || data.tool || "Шаг",
          status: (data.status || "running") as StepStatus,
          tool: data.tool || "",
          startTime: new Date().toISOString(),
          duration: data.duration || "",
          summary: data.result || data.summary || "",
          args: data.params || data.args,
          result: data.result,
        };
        setChatMeta((prev) => ({
          ...prev,
          [chatId]: {
            ...(prev[chatId] || emptyMeta()),
            steps: [...((prev[chatId] || emptyMeta()).steps || []), step],
            currentTool: data.tool || prev[chatId]?.currentTool || "",
          },
        }));
      } catch {}
    });
    
    es.addEventListener("tool_call", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setChatMeta((prev) => ({
          ...prev,
          [chatId]: {
            ...(prev[chatId] || emptyMeta()),
            currentTool: data.tool || "",
          },
        }));
        setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
      } catch {}
    });
    
    es.addEventListener("text_delta", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        fullContent += data.text || "";
        if (!hasAgentMsg) {
          hasAgentMsg = true;
          setMessages((prev) => ({
            ...prev,
            [chatId]: [...(prev[chatId] || []), {
              id: agentMsgId,
              role: "agent" as const,
              content: fullContent,
              timestamp: new Date().toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }),
              isStreaming: true,
            }],
          }));
        } else {
          setMessages((prev) => ({
            ...prev,
            [chatId]: (prev[chatId] || []).map((m) =>
              m.id === agentMsgId ? { ...m, content: fullContent } : m
            ),
          }));
        }
      } catch {}
    });
    
    es.addEventListener("task_complete", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
        setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c)));
        es.close();
        sseRef.current = null;
        // Reload to get final messages
        loadedChats.current.delete(chatId);
        loadMessages(chatId);
      } catch {}
    });
    
    es.addEventListener("cost_update", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setChatMeta((prev) => ({
          ...prev,
          [chatId]: {
            ...(prev[chatId] || emptyMeta()),
            totalCost: data.total_cost || 0,
          },
        }));
        setChats((prev) => prev.map((c) => (c.id === chatId ? { ...c, cost: data.total_cost || 0 } : c)));
      } catch {}
    });
    
    es.addEventListener("plan_update", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setChatMeta((prev) => ({
          ...prev,
          [chatId]: {
            ...(prev[chatId] || emptyMeta()),
            plan: data.phases || [],
            planCurrentPhase: data.current_phase_id || 1,
          },
        }));
      } catch {}
    });
    
    es.onerror = () => {
      es.close();
      sseRef.current = null;
    };
  }, [isSending, loadMessages]);
  
  const selectChat = useCallback((chatId: string) => {
    setActiveChat(chatId);
    loadMessages(chatId);
    // Check if this chat is running (status = working/executing) and subscribe
    setChats((prev) => {
      const chat = prev.find((c) => c.id === chatId);
      if (chat && (chat.status === "working" || chat.status === "executing" || chat.status === "thinking")) {
        // Initialize meta for live viewing
        setChatMeta((pm) => ({
          ...pm,
          [chatId]: pm[chatId] || { ...emptyMeta(), startedAt: new Date().toISOString() },
        }));
        setAgentStatus((pa) => ({ ...pa, [chatId]: "executing" }));
        subscribeToRunningChat(chatId);
      }
      return prev;
    });
  }, [loadMessages, subscribeToRunningChat]);

  useEffect(() => {
    if (activeChat) loadMessages(activeChat);
  }, [activeChat, loadMessages]);

  // ─── Create chat ──────────────────────────────────────────────────────────
  const createChat = useCallback(async (title = "Новая задача") => {
    // Guard 1: prevent concurrent creation (rapid clicks)
    if (isCreatingChat.current) return null;

    // Guard 2: if there's already an empty idle chat, just switch to it
    let existingEmpty: Chat | undefined;
    setChats((currentChats) => {
      existingEmpty = currentChats.find((c) => {
        const msgCount = messages[c.id]?.length ?? 0;
        const isIdle = !c.status || c.status === "idle";
        const isNewTitle = c.title === "Новая задача" || c.title === "Новый чат" || c.title === "New Task";
        return msgCount === 0 && isIdle && isNewTitle;
      });
      return currentChats; // no mutation
    });

    if (existingEmpty) {
      setActiveChat(existingEmpty.id);
      return existingEmpty;
    }

    isCreatingChat.current = true;
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await api.chats.create(title);
      const newChat = apiChatToUiChat(data.chat);
      setChats((prev) => [newChat, ...prev]);
      setActiveChat(newChat.id);
      setMessages((prev) => ({ ...prev, [newChat.id]: [] }));
      loadedChats.current.add(newChat.id);
      return newChat;
    } catch (err) {
      console.error("Failed to create chat:", err);
      return null;
    } finally {
      isCreatingChat.current = false;
    }
  }, [messages]);

  // ─── Delete chat ──────────────────────────────────────────────────────────
  const deleteChat = useCallback(async (chatId: string) => {
    try {
      await api.chats.delete(chatId);
      setChats((prev) => {
        const next = prev.filter((c) => c.id !== chatId);
        setActiveChat((current) => {
          if (current === chatId) return next[0]?.id ?? null;
          return current;
        });
        return next;
      });
      setMessages((prev) => {
        const next = { ...prev };
        delete next[chatId];
        return next;
      });
    } catch (err) {
      console.error("Failed to delete chat:", err);
    }
  }, []);

  // ─── Rename chat ──────────────────────────────────────────────────────────
  const renameChat = useCallback(async (chatId: string, title: string) => {
    try {
      await api.chats.rename(chatId, title);
      setChats((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, title } : c))
      );
    } catch (err) {
      console.error("Failed to rename chat:", err);
    }
  }, []);

  // ─── Send message with SSE streaming ─────────────────────────────────────
  const sendMessage = useCallback(
    async (chatId: string, text: string, variant?: string, options?: { premiumImages?: boolean; designCheck?: boolean; premiumReview?: boolean }) => {
      // Optimistically add user message
      const userMsg: Message = {
        id: `u_${Date.now()}`,
        role: "user",
        content: text,
        timestamp: new Date().toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => ({
        ...prev,
        [chatId]: [...(prev[chatId] || []), userMsg],
      }));

      // Update chat status & start timer
      setAgentStatus((prev) => ({ ...prev, [chatId]: "thinking" }));
      setChats((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, status: "thinking" } : c))
      );
      setIsSending(true);

      // Initialize meta for this task
      setChatMeta((prev) => ({
        ...prev,
        [chatId]: { ...emptyMeta(), startedAt: new Date().toISOString() },
      }));
      startTimer(chatId);

      // Placeholder for agent response
      const agentMsgId = `a_${Date.now()}`;
      const agentMsg: Message = {
        id: agentMsgId,
        role: "agent",
        content: "",
        timestamp: new Date().toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }),
        steps: [],
        plan: [],
        isStreaming: true,  // P3-FIX BUG-009: show typing indicator instead of empty bubble
      };
      setMessages((prev) => ({
        ...prev,
        [chatId]: [...(prev[chatId] || []), agentMsg],
      }));

      try {
        const response = await api.agent.send({ chatId, message: text, variant, options });
        if (!response.body) throw new Error("No response body");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullContent = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw || raw === "[DONE]") continue;

            try {
              const event = JSON.parse(raw);
              const type = event.type;

              // ── Text streaming ──────────────────────────────────────────
              if (type === "text_delta") {
                const delta = event.text || "";
                fullContent += delta;
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId ? { ...m, content: fullContent, isStreaming: true } : m
                  ),
                }));
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "executing" } : c))
                );
              } else if (type === "content") {
                const chunk = event.text || event.content || "";
                fullContent += chunk;
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId ? { ...m, content: fullContent, isStreaming: true } : m
                  ),
                }));
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
              } else if (type === "text_complete") {
                const finalText = event.content || fullContent;
                if (finalText) {
                  fullContent = finalText;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId ? { ...m, content: fullContent, isStreaming: false } : m
                    ),
                  }));
                }

              // ── Attachments (PHASE-6 FIX) ─────────────────────────────
              } else if (type === "attachments") {
                const files = event.files || [];
                if (files.length > 0) {
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId ? { ...m, attachments: files } : m
                    ),
                  }));
                }
              // ── Thinking ───────────────────────────────────────────────
              } else if (type === "thinking" || type === "thinking_start" || type === "thinking_step") {
                setAgentStatus((prev) => ({ ...prev, [chatId]: "thinking" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "thinking" } : c))
                );
                const thinkingText = event.content || event.text || "";
                if (thinkingText) {
                  setChatMeta((prev) => {
                    const meta = prev[chatId] || emptyMeta();
                    return {
                      ...prev,
                      [chatId]: {
                        ...meta,
                        thinkingContent: meta.thinkingContent
                          ? meta.thinkingContent + "\n" + thinkingText
                          : thinkingText,
                      },
                    };
                  });
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId
                        ? { ...m, thinkingContent: (m.thinkingContent || "") + (thinkingText ? "\n" + thinkingText : "") }
                        : m
                    ),
                  }));
                }

              // ── Tool calls ─────────────────────────────────────────────
              } else if (type === "tool_calls" || type === "tool_call") {
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "executing" } : c))
                );
                const toolName = event.tool || event.name || "";
                if (toolName) {
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId ? { ...m, currentTool: toolName, isStreaming: true } : m
                    ),
                  }));
                  // Also update chatMeta.currentTool for RightPanel LiveTab
                  setChatMeta((prev) => {
                    const meta = prev[chatId] || emptyMeta();
                    return { ...prev, [chatId]: { ...meta, currentTool: toolName } };
                  });
                }

              // ── Tool executing (P3-FIX BUG-016) ─────────────────────
              } else if (type === "tool_executing" || type === "tool_progress") {
                const toolName = event.tool || event.name || "";
                if (toolName) {
                  setChatMeta((prev) => {
                    const meta = prev[chatId] || emptyMeta();
                    return { ...prev, [chatId]: { ...meta, currentTool: toolName } };
                  });
                }
              // ── Step update (real-time step progress) ──────────────────
              } else if (type === "step_update") {
                const stepTool = event.tool || "";
                const stepTitle = event.title || event.step || stepTool || "Шаг";
                const step: Step = {
                  id: event.step_id || `step_${Date.now()}`,
                  title: stepTitle,
                  status: event.status || "running",
                  tool: stepTool,
                  startTime: event.start_time || new Date().toISOString(),
                  duration: event.duration || "",
                  summary: event.summary || "",
                  args: event.args || event.params,
                  result: event.result !== undefined && event.result !== null ? (typeof event.result === 'string' ? event.result : JSON.stringify(event.result)) : undefined,
                };
                setChatMeta((prev) => {
                  const meta = prev[chatId] || emptyMeta();
                  const idx = meta.steps.findIndex((s) => s.id === step.id);
                  const newSteps = idx >= 0
                    ? meta.steps.map((s, i) => (i === idx ? {
                        ...s, ...step,
                        title: step.title || s.title || s.tool || "Шаг",
                      } : s))
                    : [...meta.steps, { ...step, title: step.title || step.tool || "Шаг" }];
                  return { ...prev, [chatId]: { ...meta, steps: newSteps } };
                });
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) => {
                    if (m.id !== agentMsgId) return m;
                    const idx = (m.steps || []).findIndex((s) => s.id === step.id);
                    const newSteps = idx >= 0
                      ? (m.steps || []).map((s, i) => (i === idx ? {
                          ...s, ...step,
                          title: step.title || s.title || step.tool || "Шаг",
                        } : s))
                      : [...(m.steps || []), step];
                    return { ...m, steps: newSteps };
                  }),
                }));

              // ── Plan update ────────────────────────────────────────────
              } else if (type === "plan_update") {
                const rawPhases = event.phases || [];
                const planSteps: string[] = event.steps || event.plan || (rawPhases.length > 0
                  ? rawPhases.map((p: any) => typeof p === 'string' ? p : (p?.title || `Phase ${p?.id || '?'}`))
                  : []);
                const completedIndices: number[] = event.completed || (rawPhases.length > 0
                  ? rawPhases.filter((p: any) => p?.id < (event.current_phase_id || 1)).map((_: any, i: number) => i)
                  : []);
                setChatMeta((prev) => {
                  const meta = prev[chatId] || emptyMeta();
                  return { ...prev, [chatId]: { ...meta, plan: planSteps, planCompleted: completedIndices } };
                });
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId ? { ...m, plan: planSteps } : m
                  ),
                }));

              // ── Log entry ─────────────────────────────────────────────
              } else if (type === "log" || type === "log_entry") {
                const logEntry: LogEntry = {
                  id: event.id || `log_${Date.now()}_${Math.random().toString(36).slice(2)}`,
                  time: event.time || new Date().toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
                  level: (event.level || "info") as LogEntry["level"],
                  message: event.message || event.text || event.content || "",
                };
                if (logEntry.message) {
                  setChatMeta((prev) => {
                    const meta = prev[chatId] || emptyMeta();
                    return { ...prev, [chatId]: { ...meta, logs: [...meta.logs, logEntry] } };
                  });
                }

              // ── Cost update (real-time) ────────────────────────────────
              } else if (type === "cost_update") {
                const cost = event.total_cost ?? event.cost ?? 0;
                const inputTokens = event.input_tokens ?? 0;
                const outputTokens = event.output_tokens ?? 0;
                const iteration = event.iteration ?? 0;
                setChatMeta((prev) => {
                  const meta = prev[chatId] || emptyMeta();
                  return {
                    ...prev,
                    [chatId]: {
                      ...meta,
                      cost,
                      inputTokens: inputTokens || meta.inputTokens,
                      outputTokens: outputTokens || meta.outputTokens,
                      iterationCount: iteration || meta.iterationCount,
                    },
                  };
                });
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, cost } : c))
                );

              // ── Model info ─────────────────────────────────────────────
              } else if (type === "model_info") {
                const model = event.model || event.name || "";
                if (model) {
                  setChatMeta((prev) => {
                    const meta = prev[chatId] || emptyMeta();
                    return { ...prev, [chatId]: { ...meta, model } };
                  });
                  setChats((prev) =>
                    prev.map((c) => (c.id === chatId ? { ...c, model } : c))
                  );
                }

              // ── Task complete ──────────────────────────────────────────
              } else if (type === "task_complete") {
                const summary = event.summary || "";
                if (summary && !fullContent) {
                  fullContent = summary;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId ? { ...m, content: fullContent, isStreaming: false } : m
                    ),
                  }));
                }
                setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c))
                );
                stopTimer();
                setIsSending(false);

              // ── Done ───────────────────────────────────────────────────
              } else if (type === "done") {
                const doneContent = event.content || event.text || fullContent;
                if (doneContent) {
                  fullContent = doneContent;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId ? { ...m, content: fullContent, isStreaming: false } : m
                    ),
                  }));
                }
                setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c))
                );
                stopTimer();
                setIsSending(false);

              // ── Title ──────────────────────────────────────────────────
              } else if (type === "title") {
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, title: event.title } : c))
                );

              // ── Meta ───────────────────────────────────────────────────
              } else if (type === "meta") {
                if (event.model) {
                  setChatMeta((prev) => {
                    const meta = prev[chatId] || emptyMeta();
                    return { ...prev, [chatId]: { ...meta, model: event.model } };
                  });
                  setChats((prev) =>
                    prev.map((c) => (c.id === chatId ? { ...c, model: event.model } : c))
                  );
                }

              // ── Agent Status (P3-FIX BUG-008/BUG-012) ──────────────
              } else if (type === "agent_status") {
                const status = event.status || "";
                const detail = event.detail || "";
                if (status === "coding" || status === "browsing" || status === "deploying" || status === "researching" || status === "working") {
                  setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
                  setChats((prev) =>
                    prev.map((c) => (c.id === chatId ? { ...c, status: "executing" } : c))
                  );
                  if (detail) {
                    setChatMeta((prev) => {
                      const meta = prev[chatId] || emptyMeta();
                      return { ...prev, [chatId]: { ...meta, currentTool: detail || status } };
                    });
                  }
                } else if (status === "thinking") {
                  setAgentStatus((prev) => ({ ...prev, [chatId]: "thinking" }));
                  setChats((prev) =>
                    prev.map((c) => (c.id === chatId ? { ...c, status: "thinking" } : c))
                  );
                } else if (status === "idle" || status === "connected") {
                  // Mark as completed when agent goes idle
                  setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
                  setChats((prev) =>
                    prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c))
                  );
                  setIsSending(false);
                  stopTimer();
                } else if (status === "waiting_user") {
                  setAgentStatus((prev) => ({ ...prev, [chatId]: "idle" }));
                  setChats((prev) =>
                    prev.map((c) => (c.id === chatId ? { ...c, status: "idle" } : c))
                  );
                }
              // ── Error ──────────────────────────────────────────────────
              } else if (type === "error") {
                const errContent = event.content || event.text || event.error || "Произошла ошибка";
                if (!fullContent) {
                  fullContent = `❌ ${errContent}`;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId ? { ...m, content: fullContent, isStreaming: false } : m
                    ),
                  }));
                }
                setAgentStatus((prev) => ({ ...prev, [chatId]: "failed" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "failed" } : c))
                );
                stopTimer();

              // ── Queued / Appended / Model change ───────────────────────
              } else if (type === "queued") {
                const queuedText = event.text || "В очереди — возьму после текущей задачи";
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId ? { ...m, content: `🕐 ${queuedText}` } : m
                  ),
                }));
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
              } else if (type === "appended") {
                const appendedText = event.text || "Добавлено к текущей задаче";
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId ? { ...m, content: `📩 ${appendedText}` } : m
                  ),
                }));
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
              } else if (type === "model_change") {
                const modelMsg = event.message || "Модель изменена";
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId ? { ...m, content: `🔄 ${modelMsg}` } : m
                  ),
                }));
              }
              // Ignore: heartbeat, keepalive, usage, verification, memory_context, intent, resume
            } catch {
              // skip malformed JSON
            }
          }
        }

        // Stream ended - always mark as completed
        setAgentStatus((prev) => {
          if (prev[chatId] === "completed" || prev[chatId] === "failed") return prev;
          return { ...prev, [chatId]: "completed" };
        });
        setChats((prev) =>
          prev.map((c) => {
            if (c.id !== chatId) return c;
            if (c.status === "completed" || c.status === "failed") return c;
            return { ...c, status: "completed" };
          })
        );
        setIsSending(false);
        stopTimer();
      } catch (err) {
        console.error("SSE stream error, starting polling fallback:", err);
        // ── Polling fallback: check task status every 5s until done ──
        const pollStatus = async () => {
          try {
            const statusData = await api.chats.status(chatId);
            if (statusData.status === "idle" || statusData.status === "completed" || statusData.status === "failed") {
              // Task finished — show result
              if (statusData.last_message) {
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId ? { ...m, content: statusData.last_message!, isStreaming: false } : m
                  ),
                }));
              }
              const finalStatus = statusData.status === "failed" ? "failed" : "completed";
              setAgentStatus((prev) => ({ ...prev, [chatId]: finalStatus }));
              setChats((prev) =>
                prev.map((c) => (c.id === chatId ? { ...c, status: finalStatus, cost: statusData.total_cost || c.cost } : c))
              );
              stopTimer();
              setIsSending(false);
              return; // done polling
            }
            // Still working — update UI and poll again
            setMessages((prev) => ({
              ...prev,
              [chatId]: (prev[chatId] || []).map((m) =>
                m.id === agentMsgId ? { ...m, content: "⏳ Соединение прервалось, но задача выполняется... Ожидаю результат.", isStreaming: true } : m
              ),
            }));
            setTimeout(pollStatus, 5000);
          } catch (pollErr) {
            console.error("Polling failed:", pollErr);
            // After 3 failed polls, show error
            setMessages((prev) => ({
              ...prev,
              [chatId]: (prev[chatId] || []).map((m) =>
                m.id === agentMsgId ? { ...m, content: "❌ Соединение потеряно. Обновите страницу чтобы увидеть результат.", isStreaming: false } : m
              ),
            }));
            setAgentStatus((prev) => ({ ...prev, [chatId]: "failed" }));
            setChats((prev) =>
              prev.map((c) => (c.id === chatId ? { ...c, status: "failed" } : c))
            );
            stopTimer();
            setIsSending(false);
          }
        };
        // Start polling after 2s delay
        setTimeout(pollStatus, 2000);
        return; // Don't go to finally yet — polling handles cleanup
      } finally {
        setIsSending(false);
        setTimeout(() => loadChats(), 2000);
      }
    },
    [isSending, loadChats, startTimer, stopTimer]
  );

  // ─── Stop agent ───────────────────────────────────────────────────────────
  const stopAgent = useCallback(async (chatId: string) => {
    try {
      await api.chats.stop(chatId);
      setAgentStatus((prev) => ({ ...prev, [chatId]: "idle" }));
      setChats((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, status: "idle" } : c))
      );
      setIsSending(false);
      stopTimer();
    } catch (err) {
      console.error("Failed to stop agent:", err);
    }
  }, [stopTimer]);

  // ─── Helper: get formatted elapsed for active chat ────────────────────────
  const getElapsed = useCallback((chatId: string): string => {
    const meta = chatMeta[chatId];
    if (!meta?.startedAt) return "";
    return formatElapsed(meta.elapsed);
  }, [chatMeta]);

  // Cleanup SSE subscription on unmount
  useEffect(() => {
    return () => {
      if (sseRef.current) {
        sseRef.current.close();
        sseRef.current = null;
      }
    };
  }, []);
  
  return {
    chats,
    activeChat,
    messages,
    isLoading,
    isSending,
    agentStatus,
    chatMeta,
    loadChats,
    selectChat,
    createChat,
    deleteChat,
    renameChat,
    sendMessage,
    stopAgent,
    setActiveChat,
    getElapsed,
  };
}