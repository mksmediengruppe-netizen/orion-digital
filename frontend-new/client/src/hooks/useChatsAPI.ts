import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import type { Chat, Message } from "@/lib/mockData";

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

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useChatsAPI() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeChat, setActiveChat] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, Message[]>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [agentStatus, setAgentStatus] = useState<Record<string, string>>({});
  const loadedChats = new Set<string>();

  // ─── Load chats list ─────────────────────────────────────────────────────
  const loadChats = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await api.chats.list();
      const uiChats = (data.chats || []).map(apiChatToUiChat);
      setChats(uiChats);
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

  useEffect(() => {
    loadChats();
  }, [loadChats]);

  // ─── Load messages for a chat ─────────────────────────────────────────────
  const loadMessages = useCallback(async (chatId: string) => {
    if (loadedChats.has(chatId)) return;
    loadedChats.add(chatId);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await api.chats.get(chatId);
      const chat = data.chat || data;
      const msgs: ApiMessage[] = chat.messages || [];
      setMessages((prev) => ({
        ...prev,
        [chatId]: msgs.map(apiMessageToUiMessage),
      }));
    } catch (err) {
      console.error("Failed to load messages:", err);
      loadedChats.delete(chatId); // allow retry
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Select chat ──────────────────────────────────────────────────────────
  const selectChat = useCallback((chatId: string) => {
    setActiveChat(chatId);
    loadMessages(chatId);
  }, [loadMessages]);

  // Auto-load messages when activeChat changes
  useEffect(() => {
    if (activeChat) {
      loadMessages(activeChat);
    }
  }, [activeChat, loadMessages]);

  // ─── Create chat ──────────────────────────────────────────────────────────
  const createChat = useCallback(async (title = "Новый чат") => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await api.chats.create(title);
      const newChat = apiChatToUiChat(data.chat);
      setChats((prev) => [newChat, ...prev]);
      setActiveChat(newChat.id);
      setMessages((prev) => ({ ...prev, [newChat.id]: [] }));
      loadedChats.add(newChat.id);
      return newChat;
    } catch (err) {
      console.error("Failed to create chat:", err);
      return null;
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
    async (chatId: string, text: string) => {
      if (isSending) return;

      // Optimistically add user message
      const userMsg: Message = {
        id: `u_${Date.now()}`,
        role: "user",
        content: text,
        timestamp: new Date().toLocaleTimeString("ru", {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };
      setMessages((prev) => ({
        ...prev,
        [chatId]: [...(prev[chatId] || []), userMsg],
      }));

      // Update chat status
      setAgentStatus((prev) => ({ ...prev, [chatId]: "thinking" }));
      setChats((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, status: "thinking" } : c))
      );
      setIsSending(true);

      // Placeholder for agent response
      const agentMsgId = `a_${Date.now()}`;
      const agentMsg: Message = {
        id: agentMsgId,
        role: "agent",
        content: "",
        timestamp: new Date().toLocaleTimeString("ru", {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };
      setMessages((prev) => ({
        ...prev,
        [chatId]: [...(prev[chatId] || []), agentMsg],
      }));

      try {
        const response = await api.agent.send({ chatId, message: text });

        if (!response.body) {
          throw new Error("No response body");
        }

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

              if (type === "text_delta") {
                // Streaming text chunk
                const delta = event.text || "";
                fullContent += delta;
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId
                      ? { ...m, content: fullContent }
                      : m
                  ),
                }));
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "executing" } : c))
                );
              } else if (type === "content") {
                // Full content chunk (non-streaming)
                const chunk = event.text || event.content || "";
                fullContent += chunk;
                setMessages((prev) => ({
                  ...prev,
                  [chatId]: (prev[chatId] || []).map((m) =>
                    m.id === agentMsgId
                      ? { ...m, content: fullContent }
                      : m
                  ),
                }));
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
              } else if (type === "text_complete") {
                // Text generation complete (may have final content)
                const finalText = event.content || fullContent;
                if (finalText) {
                  fullContent = finalText;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId
                        ? { ...m, content: fullContent }
                        : m
                    ),
                  }));
                }
              } else if (type === "thinking" || type === "thinking_start" || type === "thinking_step") {
                setAgentStatus((prev) => ({ ...prev, [chatId]: "thinking" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "thinking" } : c))
                );
              } else if (type === "tool_calls") {
                setAgentStatus((prev) => ({ ...prev, [chatId]: "executing" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "executing" } : c))
                );
              } else if (type === "task_complete") {
                // Agent finished the task
                const summary = event.summary || "";
                if (summary && !fullContent) {
                  fullContent = summary;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId
                        ? { ...m, content: fullContent }
                        : m
                    ),
                  }));
                }
                setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c))
                );
              } else if (type === "done") {
                // Simple done event
                const doneContent = event.content || event.text || fullContent;
                if (doneContent) {
                  fullContent = doneContent;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId
                        ? { ...m, content: fullContent }
                        : m
                    ),
                  }));
                }
                setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c))
                );
              } else if (type === "title") {
                // Auto-generated title
                setChats((prev) =>
                  prev.map((c) =>
                    c.id === chatId ? { ...c, title: event.title } : c
                  )
                );
              } else if (type === "meta") {
                // Model/variant metadata
                if (event.model) {
                  setChats((prev) =>
                    prev.map((c) =>
                      c.id === chatId ? { ...c, model: event.model } : c
                    )
                  );
                }
              } else if (type === "error") {
                const errContent = event.content || event.text || event.error || "Произошла ошибка";
                if (!fullContent) {
                  fullContent = `❌ ${errContent}`;
                  setMessages((prev) => ({
                    ...prev,
                    [chatId]: (prev[chatId] || []).map((m) =>
                      m.id === agentMsgId
                        ? { ...m, content: fullContent }
                        : m
                    ),
                  }));
                }
                setAgentStatus((prev) => ({ ...prev, [chatId]: "failed" }));
                setChats((prev) =>
                  prev.map((c) => (c.id === chatId ? { ...c, status: "failed" } : c))
                );
              }
              // Ignore: heartbeat, keepalive, usage, verification, memory_context, intent, resume
            } catch {
              // skip malformed JSON
            }
          }
        }

        // If we got content but no explicit done event, mark as completed
        if (fullContent && agentStatus[chatId] !== "completed" && agentStatus[chatId] !== "failed") {
          setAgentStatus((prev) => ({ ...prev, [chatId]: "completed" }));
          setChats((prev) =>
            prev.map((c) => (c.id === chatId ? { ...c, status: "completed" } : c))
          );
        }

      } catch (err) {
        console.error("Send message error:", err);
        const errMsg = "Ошибка соединения с сервером. Попробуйте ещё раз.";
        setMessages((prev) => ({
          ...prev,
          [chatId]: (prev[chatId] || []).map((m) =>
            m.id === agentMsgId
              ? { ...m, content: errMsg }
              : m
          ),
        }));
        setAgentStatus((prev) => ({ ...prev, [chatId]: "failed" }));
        setChats((prev) =>
          prev.map((c) => (c.id === chatId ? { ...c, status: "failed" } : c))
        );
      } finally {
        setIsSending(false);
        // Reload chats to get updated cost/title after 2s
        setTimeout(() => loadChats(), 2000);
      }
    },
    [isSending, loadChats, agentStatus]
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
    } catch (err) {
      console.error("Failed to stop agent:", err);
    }
  }, []);

  return {
    chats,
    activeChat,
    messages,
    isLoading,
    isSending,
    agentStatus,
    loadChats,
    selectChat,
    createChat,
    deleteChat,
    renameChat,
    sendMessage,
    stopAgent,
    setActiveChat,
  };
}
