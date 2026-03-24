// Design: "Warm Intelligence" — warm off-white, indigo accent
// Three-column layout: Sidebar | Chat | Right Panel (resizable)
// NEW: CommandPalette (Cmd+K), TakeoverMode, AgentInterrupt, SkeletonChat, keyboard shortcuts, pinned chats, inline edit

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { cn } from "@/lib/utils";
import { CHATS, PROJECTS, type Step, type Message, type AgentStatus, type Chat, type Project, type ViewerArtifact } from "@/lib/mockData";
import { Sidebar } from "@/components/orion/Sidebar";
import { ChatHeader, type ModelKey } from "@/components/orion/ChatHeader";
import { ChatMessage } from "@/components/orion/ChatMessage";
import { Composer } from "@/components/orion/Composer";
import { RightPanel } from "@/components/orion/RightPanel";
import { AdminDashboard } from "@/components/orion/AdminDashboard";
import { StatusBadge } from "@/components/orion/StatusBadge";
import { useExecutionSimulation } from "@/hooks/useExecutionSimulation";
import { useResizablePanel } from "@/hooks/useResizablePanel";
import { PlanFooter } from "@/components/orion/PlanFooter";
import { useLiveTimerWithReset } from "@/hooks/useLiveTimer";
import { CommandPalette } from "@/components/orion/CommandPalette";
import { TakeoverBanner, TakeoverPanel, TakeoverButton } from "@/components/orion/TakeoverMode";
import { AgentInterruptDialog, useAgentInterrupt } from "@/components/orion/AgentInterruptDialog";
import { SkeletonChat } from "@/components/orion/SkeletonChat";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, BookOpen, Calendar } from "lucide-react";
import { PlaybooksPanel } from "@/components/orion/PlaybooksPanel";
import { ScheduledTasksPanel } from "@/components/orion/ScheduledTasksPanel";
import { useScheduleAPI } from "@/hooks/useScheduleAPI";
import { toast } from "sonner";
import { useTheme } from "@/contexts/ThemeContext";
import { type AppNotification } from "@/components/orion/NotificationCenter";
import { SSEReconnectingBanner, useSSEConnectionDemo, type SSEConnectionState } from "@/components/orion/SSEReconnectingBanner";
import { UserSettingsPanel } from "@/components/orion/UserSettingsPanel";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function collectSteps(messages: Message[]): Step[] {
  return messages.flatMap(m => m.steps ?? []);
}

function extractPlan(messages: Message[]): string[] {
  for (const msg of [...messages].reverse()) {
    if (msg.plan && msg.plan.length > 0) return msg.plan;
  }
  return [];
}

function countCompletedSteps(messages: Message[]): number {
  let count = 0;
  for (const msg of messages) {
    if (msg.steps) {
      count += msg.steps.filter(s => s.status !== "running" && s.status !== "queued").length;
    }
  }
  return count;
}

// ─── Per-chat initial messages ────────────────────────────────────────────────

const INITIAL_MESSAGES: Record<string, Message[]> = {
  c1: [],
  c2: [
    {
      id: "c2m1",
      role: "user",
      content: "Настрой SSL сертификат для домена example.com на сервере 185.22.xx.xx",
      timestamp: "11:10",
    },
    {
      id: "c2m2",
      role: "agent",
      content: `## SSL сертификат настроен

:::success Let's Encrypt сертификат получен и установлен:::

Сертификат действителен **90 дней** и будет автоматически обновляться через cron.

### Детали сертификата

| Параметр | Значение |
|---|---|
| Домен | example.com |
| Тип | Let's Encrypt (DV) |
| Действителен до | 22.06.2026 |
| Алгоритм | RSA 2048 |
| Автообновление | ✓ Настроено |

### Конфигурация nginx

\`\`\`nginx
server {
    listen 443 ssl;
    server_name example.com;
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
}
\`\`\`

> Сайт доступен по [https://example.com](https://example.com). HTTP автоматически редиректит на HTTPS.`,
      timestamp: "11:10",
      plan: ["Установить certbot", "Получить SSL сертификат", "Настроить nginx для HTTPS", "Проверить автообновление"],
      steps: [
        { id: "s_ssl1", title: "Установил certbot", status: "success", tool: "Terminal", startTime: "11:10:30", duration: "12.4s", summary: "apt-get install certbot python3-certbot-nginx", goldenPath: true, args: { command: "apt-get install -y certbot python3-certbot-nginx" }, result: "certbot 2.6.0 установлен успешно" },
        { id: "s_ssl2", title: "Получил сертификат", status: "success", tool: "Terminal", startTime: "11:11:00", duration: "8.2s", summary: "certbot --nginx -d example.com", args: { domain: "example.com" }, result: "Сертификат получен, действителен до 22.06.2026" },
        { id: "s_ssl3", title: "Настроил nginx", status: "success", tool: "SSH", startTime: "11:11:15", duration: "3.1s", summary: "Обновил конфигурацию nginx для HTTPS", result: "nginx.conf обновлён, перезапущен" },
        { id: "s_ssl4", title: "Проверил HTTPS", status: "success", tool: "Browser", startTime: "11:11:20", duration: "2.0s", summary: "Открыл https://example.com — сертификат валиден", args: { url: "https://example.com" }, result: "HTTP → HTTPS redirect работает, сертификат валиден ✓" },
      ],
    },
    {
      id: "c2m3",
      role: "agent",
      content: "SSL сертификат успешно настроен. Сайт доступен по HTTPS, сертификат действителен до 22 июня 2026. Автообновление настроено через cron.",
      timestamp: "11:15",
    },
  ],
  c3: [
    {
      id: "c3m1",
      role: "user",
      content: "Оптимизируй скорость загрузки сайта. Нужно подключить Redis для кэширования.",
      timestamp: "вчера",
    },
    {
      id: "c3m2",
      role: "agent",
      content: `## Ошибка подключения к Redis

:::error Задача завершена с ошибкой — Redis недоступен:::

Не удалось подключиться к Redis на порту **6379**. Сервис не запущен или заблокирован файрволом.

### Диагностика

\`\`\`bash
$ redis-cli ping
Could not connect to Redis at 127.0.0.1:6379: Connection refused
\`\`\`

### Рекомендации

1. Установить Redis: \`apt-get install redis-server\`
2. Запустить сервис: \`systemctl start redis\`
3. Проверить файрвол: \`ufw allow 6379\``,
      timestamp: "вчера",
      steps: [
        { id: "s_r1", title: "Проверил Redis", status: "failed", tool: "Terminal", startTime: "09:15:00", duration: "1.2s", summary: "redis-cli ping → Connection refused", result: "Redis не запущен" },
        { id: "s_r2", title: "Проверил файрвол", status: "warning", tool: "SSH", startTime: "09:15:05", duration: "0.8s", summary: "ufw status — порт 6379 закрыт", warning: "Порт 6379 заблокирован файрволом" },
      ],
    },
  ],
};

// ─── Main Component ───────────────────────────────────────────────────────────

export default function Home() {
  const [activeChat, setActiveChat] = useState("c1");
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeStep, setActiveStep] = useState<string | undefined>(undefined);
  const [showAdmin, setShowAdmin] = useState(false);
  const [rightPanelTab, setRightPanelTab] = useState("live");
  const [chatMessages, setChatMessages] = useState<Record<string, Message[]>>(INITIAL_MESSAGES);
  const [simStatusOverride, setSimStatusOverride] = useState<AgentStatus | undefined>(undefined);
  const [selectedModel, setSelectedModel] = useState<ModelKey>("standard");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [isTakeover, setIsTakeover] = useState(false);
  const [pinnedChats, setPinnedChats] = useState<Set<string>>(new Set(["c2"]));
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [showPlaybooks, setShowPlaybooks] = useState(false);
  const [showScheduled, setShowScheduled] = useState(false);

  // ─── Schedule API ─────────────────────────────────────────────────────────
  const scheduleAPI = useScheduleAPI();
  const [showSettings, setShowSettings] = useState(false);
  const [pendingArtifact, setPendingArtifact] = useState<ViewerArtifact | null>(null);

  // ─── SSE connection state (demo) ─────────────────────────────────────────
  const { sseState, showBanner: sseBannerVisible, simulateDisconnect, simulateFailed, simulateOffline, retry: retrySSE, setShowBanner: setSSEBannerVisible } = useSSEConnectionDemo();

  // ─── Budget enforcement ───────────────────────────────────────────────────
  // Simulates current user's budget: $5.00 limit, $4.80 already spent
  const [userBudgetLimit] = useState(5.00);
  const [userBudgetSpent, setUserBudgetSpent] = useState(4.80);
  const budgetExhausted = userBudgetSpent >= userBudgetLimit;
  const budgetWarning = !budgetExhausted && userBudgetSpent / userBudgetLimit >= 0.8;
  const budgetExhaustedNotifSent = useRef(false);
  const budgetWarningNotifSent = useRef(false);

  // ─── Notifications ────────────────────────────────────────────────────────
  const [notifications, setNotifications] = useState<AppNotification[]>([]);

  const pushNotification = useCallback((n: Omit<AppNotification, "id" | "timestamp" | "read">) => {
    setNotifications(prev => [{ ...n, id: `n${Date.now()}`, timestamp: new Date(), read: false }, ...prev]);
  }, []);

  const handleMarkRead = useCallback((id: string) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  }, []);

  const handleMarkAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  }, []);

  const handleDismissNotif = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const handleClearAllNotifs = useCallback(() => setNotifications([]), []);

  // Trigger budget warning notification at 80%
  useEffect(() => {
    if (budgetWarning && !budgetWarningNotifSent.current) {
      budgetWarningNotifSent.current = true;
      const pct = Math.round((userBudgetSpent / userBudgetLimit) * 100);
      pushNotification({
        type: "budget_warning",
        title: `Бюджет ${pct}%: Алексей Петров`,
        body: `Пользователь Алексей Петров использовал ${pct}% бюджета ($${userBudgetSpent.toFixed(2)} из $${userBudgetLimit.toFixed(2)}). Рекомендуем пополнить бюджет.`,
        userName: "Алексей Петров",
        userEmail: "alex@company.ru",
        adminEmail: "admin@company.ru",
        amount: userBudgetSpent,
        limit: userBudgetLimit,
        emailSent: true,
      });
    }
    if (!budgetWarning) {
      budgetWarningNotifSent.current = false;
    }
  }, [budgetWarning, pushNotification, userBudgetLimit, userBudgetSpent]);

  // Trigger budget exhaustion notification once
  useEffect(() => {
    if (budgetExhausted && !budgetExhaustedNotifSent.current) {
      budgetExhaustedNotifSent.current = true;
      pushNotification({
        type: "budget_exhausted",
        title: "Бюджет исчерпан: Алексей Петров",
        body: `Пользователь Алексей Петров израсходовал весь бюджет ($${userBudgetLimit.toFixed(2)}). Все задачи остановлены.`,
        userName: "Алексей Петров",
        userEmail: "alex@company.ru",
        adminEmail: "admin@company.ru",
        amount: userBudgetSpent,
        limit: userBudgetLimit,
        emailSent: true,
      });
    }
    if (!budgetExhausted) {
      budgetExhaustedNotifSent.current = false;
    }
  }, [budgetExhausted, pushNotification, userBudgetLimit, userBudgetSpent]);

  const handleAdminRefill = useCallback(() => {
    setShowAdmin(true);
  }, []);

  const handleRefillBudget = useCallback((amount: number) => {
    setUserBudgetSpent(0);
    toast.success(`Бюджет пополнен на $${amount.toFixed(2)}. Задачи разблокированы.`);
  }, []);

  // Open artifact in right panel Artifacts tab
  const handleArtifactOpen = useCallback((artifact: ViewerArtifact) => {
    setPendingArtifact(artifact);
    setRightPanelTab("artifacts");
    setRightPanelOpen(true);
  }, []);

  // Projects & chats state (lifted up for sidebar)
  const [projects, setProjects] = useState<Project[]>(PROJECTS);
  const [allChats, setAllChats] = useState<Chat[]>(CHATS);

  const { theme, toggleTheme } = useTheme();

  // Agent interrupt
  const { interrupt, triggerInterrupt, handleAnswer, handleDismiss } = useAgentInterrupt();

  const handleCreateProject = useCallback((name: string) => {
    const newProject: Project = {
      id: `p${Date.now()}`,
      name,
      type: "custom",
      chatCount: 0,
      lastActivity: "только что",
      color: "#6366f1",
    };
    setProjects(prev => [...prev, newProject]);
    toast.success(`Проект «${name}» создан`);
  }, []);

  const handleCreateChat = useCallback((projectId: string, title: string) => {
    const newChat: Chat = {
      id: `c${Date.now()}`,
      projectId,
      title,
      mode: "premium",
      status: "idle",
      cost: 0,
      duration: "0s",
      lastMessage: "",
      timestamp: "только что",
      model: "GPT-5.4",
    };
    setAllChats(prev => [...prev, newChat]);
    setActiveChat(newChat.id);
    setChatMessages(prev => ({ ...prev, [newChat.id]: [] }));
    toast.success(`Задача «${title}» создана`);
  }, []);

  const handleRenameChat = useCallback((chatId: string, title: string) => {
    setAllChats(prev => prev.map(c => c.id === chatId ? { ...c, title } : c));
    toast.success("Переименовано");
  }, []);

  const handleDeleteChat = useCallback((chatId: string) => {
    setAllChats(prev => prev.filter(c => c.id !== chatId));
    if (activeChat === chatId) {
      const remaining = allChats.filter(c => c.id !== chatId);
      setActiveChat(remaining[0]?.id ?? "c1");
    }
    toast.success("Задача удалена");
  }, [activeChat, allChats]);

  const handleMoveChat = useCallback((chatId: string, projectId: string) => {
    setAllChats(prev => prev.map(c => c.id === chatId ? { ...c, projectId } : c));
    const project = projects.find(p => p.id === projectId);
    toast.success(`Перемещено в «${project?.name ?? projectId}»`);
  }, [projects]);

  const handleRenameProject = useCallback((projectId: string, name: string) => {
    setProjects(prev => prev.map(p => p.id === projectId ? { ...p, name } : p));
    toast.success(`Проект переименован`);
  }, []);

  const handleDeleteProject = useCallback((projectId: string) => {
    setProjects(prev => prev.filter(p => p.id !== projectId));
    setAllChats(prev => prev.filter(c => c.projectId !== projectId));
    if (allChats.find(c => c.projectId === projectId && c.id === activeChat)) {
      const remaining = allChats.filter(c => c.projectId !== projectId);
      setActiveChat(remaining[0]?.id ?? "c1");
    }
    toast.success("Проект удалён");
  }, [allChats, activeChat]);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Resizable right panel
  const { width: rightPanelWidth, isResizing, handleMouseDown: handlePanelResize } = useResizablePanel({
    defaultWidth: 360,
    minWidth: 280,
    maxWidth: 700,
    side: "left",
  });

  // Simulation callbacks
  const handleSimMessages = useCallback((msgs: Message[]) => {
    setChatMessages(prev => ({ ...prev, c1: msgs }));
  }, []);
  const handleSimStatus = useCallback((status: AgentStatus) => {
    setSimStatusOverride(status);
  }, []);
  const handleSimActiveStep = useCallback((stepId: string | undefined) => {
    setActiveStep(stepId);
  }, []);
  const handleSimRightTab = useCallback((tab: string) => {
    setRightPanelTab(tab);
    setRightPanelOpen(true);
  }, []);

  const { simState, start: startSim, reset: resetSim } = useExecutionSimulation({
    onMessagesChange: handleSimMessages,
    onStatusChange: handleSimStatus,
    onActiveStepChange: handleSimActiveStep,
    onRightPanelTabChange: handleSimRightTab,
  });

  // Live timer — ticks while simulation is running
  const { time: liveTime, reset: resetTimer } = useLiveTimerWithReset(simState === "running");

  // Task completion notification
  const prevSimState = useRef<string>("idle");
  useEffect(() => {
    if (prevSimState.current === "running" && simState === "done") {
      const finalTime = liveTime || "4:12";
      const finalCost = "$1.24";
      // Deduct $1.24 from user budget
      setUserBudgetSpent(prev => {
        const next = prev + 1.24;
        if (next >= userBudgetLimit) {
          setTimeout(() => toast.error("Бюджет исчерпан. Новые задачи заблокированы.", { duration: 8000, action: { label: "Админка", onClick: () => setShowAdmin(true) } }), 500);
        }
        return next;
      });
      toast.success(
        `Задача завершена · ${finalTime} · ${finalCost}`,
        {
          duration: 8000,
          description: "Установка Bitrix CMS выполнена успешно. Все шаги пройдены.",
          action: {
            label: "Результат",
            onClick: () => { setRightPanelOpen(true); setRightPanelTab("result"); },
          },
        }
      );
    }
    prevSimState.current = simState;
  }, [simState]);

  // Agent interrupt demo — triggers mid-simulation
  const interruptTriggered = useRef(false);
  useEffect(() => {
    if (simState === "running" && !interruptTriggered.current) {
      const timer = setTimeout(() => {
        interruptTriggered.current = true;
        triggerInterrupt(
          "Обнаружена существующая база данных 'bitrix_db'. Как поступить?",
          [
            "Удалить и создать заново (рекомендуется)",
            "Использовать существующую базу данных",
            "Создать новую с другим именем",
          ]
        );
      }, 12000);
      return () => clearTimeout(timer);
    }
    if (simState === "idle") {
      interruptTriggered.current = false;
    }
  }, [simState]);

  const handleStartSimulation = useCallback(() => {
    if (budgetExhausted) {
      toast.error("Бюджет исчерпан. Пополните бюджет у администратора.", { action: { label: "Админка", onClick: () => setShowAdmin(true) } });
      return;
    }
    setChatMessages(prev => ({ ...prev, c1: [] }));
    setSimStatusOverride(undefined);
    setActiveStep(undefined);
    setRightPanelTab("live");
    setRightPanelOpen(true);
    toast.info("Симуляция запущена — наблюдайте за шагами агента");
    setTimeout(() => startSim(), 100);
  }, [startSim, budgetExhausted]);

  const handleResetSimulation = useCallback(() => {
    resetSim();
    setChatMessages(prev => ({ ...prev, c1: [] }));
    setSimStatusOverride(undefined);
    setActiveStep(undefined);
    setRightPanelTab("live");
    interruptTriggered.current = false;
  }, [resetSim]);

  // ─── Keyboard shortcuts ───────────────────────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMac = navigator.platform.includes("Mac");
      const mod = isMac ? e.metaKey : e.ctrlKey;

      // Cmd+K — command palette
      if (mod && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen(v => !v);
      }
      // Cmd+B — toggle sidebar
      if (mod && e.key === "b") {
        e.preventDefault();
        setSidebarCollapsed(v => !v);
      }
      // Cmd+\ — toggle right panel
      if (mod && e.key === "\\") {
        e.preventDefault();
        setRightPanelOpen(v => !v);
      }
      // Cmd+N — new chat
      if (mod && e.key === "n") {
        e.preventDefault();
        const firstProject = projects[0];
        if (firstProject) handleCreateChat(firstProject.id, "Новая задача");
      }
      // Cmd+E — export chat
      if (mod && e.key === "e") {
        e.preventDefault();
        handleExportChat();
      }
      // Cmd+/ — show shortcuts (via palette)
      if (mod && e.key === "/") {
        e.preventDefault();
        setCommandPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [projects, handleCreateChat]);

  const handleExportChat = useCallback(() => {
    const chat = allChats.find(c => c.id === activeChat);
    const msgs = chatMessages[activeChat] ?? [];
    const lines = [
      `# ${chat?.title ?? "Чат"}`,
      `**Проект:** ${projects.find(p => p.id === chat?.projectId)?.name ?? ""}`,
      `**Экспортировано:** ${new Date().toLocaleString("ru")}`,
      `**Стоимость:** $${chat?.cost?.toFixed(2) ?? "0.00"}`,
      "",
      "---",
      "",
      ...msgs.map(m => {
        const role = m.role === "user" ? "**Вы**" : m.role === "agent" ? "**Агент**" : "**Система**";
        return `${role} · ${m.timestamp}\n\n${m.content}\n`;
      }),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(chat?.title ?? "chat").replace(/[^а-яёa-z0-9]/gi, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Чат экспортирован в Markdown");
  }, [activeChat, allChats, chatMessages, projects]);

  // ─── Chat selection with skeleton ────────────────────────────────────────

  const handleChatSelect = useCallback((id: string) => {
    if (id === activeChat) return;
    setIsLoadingChat(true);
    setActiveChat(id);
    setActiveStep(undefined);
    setRightPanelTab("live");
    setTimeout(() => setIsLoadingChat(false), 400);
  }, [activeChat]);

  // ─── Message edit ─────────────────────────────────────────────────────────

  const handleMessageEdit = useCallback((messageId: string, newContent: string) => {
    setChatMessages(prev => ({
      ...prev,
      [activeChat]: (prev[activeChat] ?? []).map(m =>
        m.id === messageId ? { ...m, content: newContent } : m
      ),
    }));
  }, [activeChat]);

  // ─── Pinned chats ─────────────────────────────────────────────────────────

  const handlePinChat = useCallback((chatId: string) => {
    setPinnedChats(prev => {
      const next = new Set(prev);
      if (next.has(chatId)) {
        next.delete(chatId);
        toast.success("Чат откреплён");
      } else {
        next.add(chatId);
        toast.success("Чат закреплён");
      }
      return next;
    });
  }, []);

  // ─── Derived state ────────────────────────────────────────────────────────

  const chat = allChats.find(c => c.id === activeChat) ?? allChats[0] ?? CHATS[0];
  const messages = chatMessages[activeChat] ?? [];
  const currentSteps = useMemo(() => collectSteps(messages), [messages]);
  const currentPlan = useMemo(() => extractPlan(messages), [messages]);
  const completedStepsCount = useMemo(() => countCompletedSteps(messages), [messages]);
  const runningStep = useMemo(() => currentSteps.find(s => s.status === "running"), [currentSteps]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, activeChat]);

  const handleStepClick = (step: Step) => {
    setActiveStep(step.id);
    setRightPanelOpen(true);
    setRightPanelTab("steps");
  };

  const handleSend = (text: string) => {
    if (budgetExhausted) {
      toast.error("Бюджет исчерпан. Задачи заблокированы.", { action: { label: "Админка", onClick: () => setShowAdmin(true) } });
      return;
    }
    const newMsg: Message = {
      id: `m${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }),
    };
    setChatMessages(prev => ({
      ...prev,
      [activeChat]: [...(prev[activeChat] ?? []), newMsg],
    }));
    toast.success("Задача отправлена агенту");
  };

  const headerStatus = activeChat === "c1" && simStatusOverride ? simStatusOverride : chat.status;
  const isRunning = activeChat === "c1" && simState === "running";
  const showTypingIndicator =
    activeChat === "c1" &&
    simState === "running" &&
    messages.length > 0 &&
    messages[messages.length - 1]?.role === "user";

  if (showAdmin) {
    return (
      <div className="h-screen flex overflow-hidden">
        <AdminDashboard onBack={() => setShowAdmin(false)} onRefillBudget={handleRefillBudget} />
      </div>
    );
  }

  if (showSettings) {
    return (
      <div className="h-screen flex overflow-hidden">
        {/* Sidebar stays visible for navigation context */}
        <div className="w-72 shrink-0 border-r border-[#E8E6E1] dark:border-[#2a2d3a] h-full overflow-hidden">
          <Sidebar
            activeChat={activeChat}
            onChatSelect={(id) => { setShowSettings(false); handleChatSelect(id); }}
            onAdminClick={() => { setShowSettings(false); setShowAdmin(true); }}
            collapsed={false}
            onCollapse={() => {}}
            projects={projects}
            chats={allChats}
            onCreateProject={handleCreateProject}
            onCreateChat={handleCreateChat}
            onRenameChat={handleRenameChat}
            onDeleteChat={handleDeleteChat}
            onMoveChat={handleMoveChat}
            onRenameProject={handleRenameProject}
            onDeleteProject={handleDeleteProject}
            pinnedChats={pinnedChats}
            onPinChat={handlePinChat}
            onCommandPalette={() => setCommandPaletteOpen(true)}
            onSettingsClick={() => setShowSettings(false)}
            notifications={notifications}
            onMarkRead={handleMarkRead}
            onMarkAllRead={handleMarkAllRead}
            onDismissNotif={handleDismissNotif}
            onClearAllNotifs={handleClearAllNotifs}
          />
        </div>
        <div className="flex-1 overflow-hidden">
          <UserSettingsPanel onClose={() => setShowSettings(false)} />
        </div>
      </div>
    );
  }

  if (showPlaybooks) {
    return (
      <div className="h-screen flex overflow-hidden">
        <div className="w-72 shrink-0 border-r border-[#E8E6E1] h-full overflow-hidden">
          <Sidebar
            activeChat={activeChat}
            onChatSelect={handleChatSelect}
            onAdminClick={() => setShowAdmin(true)}
            collapsed={sidebarCollapsed}
            onCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
            projects={projects}
            chats={allChats}
            onCreateProject={handleCreateProject}
            onCreateChat={handleCreateChat}
            onRenameChat={handleRenameChat}
            onDeleteChat={handleDeleteChat}
            onMoveChat={handleMoveChat}
            onRenameProject={handleRenameProject}
            onDeleteProject={handleDeleteProject}
            pinnedChats={pinnedChats}
            onPinChat={handlePinChat}
            onCommandPalette={() => setCommandPaletteOpen(true)}
          />
        </div>
        <div className="flex-1 overflow-hidden">
          <PlaybooksPanel
            onRunPlaybook={(prompt, title) => {
              setShowPlaybooks(false);
              handleSend(prompt);
            }}
            onClose={() => setShowPlaybooks(false)}
          />
        </div>
      </div>
    );
  }

  if (showScheduled) {
    return (
      <div className="h-screen flex overflow-hidden">
        <div className="w-72 shrink-0 border-r border-[#E8E6E1] dark:border-[#2a2d3a] h-full overflow-hidden">
          <Sidebar
            activeChat={activeChat}
            onChatSelect={(id) => { setShowScheduled(false); handleChatSelect(id); }}
            onAdminClick={() => { setShowScheduled(false); setShowAdmin(true); }}
            collapsed={false}
            onCollapse={() => {}}
            projects={projects}
            chats={allChats}
            onCreateProject={handleCreateProject}
            onCreateChat={handleCreateChat}
            onRenameChat={handleRenameChat}
            onDeleteChat={handleDeleteChat}
            onMoveChat={handleMoveChat}
            onRenameProject={handleRenameProject}
            onDeleteProject={handleDeleteProject}
            pinnedChats={pinnedChats}
            onPinChat={handlePinChat}
            onCommandPalette={() => setCommandPaletteOpen(true)}
            onScheduled={() => {}}
            onSettingsClick={() => { setShowScheduled(false); setShowSettings(true); }}
            notifications={notifications}
            onMarkRead={handleMarkRead}
            onMarkAllRead={handleMarkAllRead}
            onDismissNotif={handleDismissNotif}
            onClearAllNotifs={handleClearAllNotifs}
          />
        </div>
        <div className="flex-1 overflow-hidden">
          <ScheduledTasksPanel
            onClose={() => setShowScheduled(false)}
            externalTasks={scheduleAPI.error ? undefined : scheduleAPI.tasks}
            onToggle={scheduleAPI.toggleTask}
            onRunNow={scheduleAPI.runNow}
            onDelete={scheduleAPI.deleteTask}
            onSave={async (data, editingId) => {
              if (editingId) {
                await scheduleAPI.updateTask(editingId, {
                  title: data.title,
                  prompt: data.prompt,
                  cron: data.cron,
                  category: data.category,
                });
              } else {
                await scheduleAPI.createTask({
                  title: data.title,
                  prompt: data.prompt,
                  cron: data.cron,
                  category: data.category,
                });
              }
            }}
            apiLoading={scheduleAPI.loading}
            apiError={scheduleAPI.error}
          />
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Global Command Palette */}
      <CommandPalette
        open={commandPaletteOpen}
        onOpenChange={setCommandPaletteOpen}
        chats={allChats}
        projects={projects}
        activeChat={activeChat}
        onChatSelect={handleChatSelect}
        onCreateChat={() => {
          const firstProject = projects[0];
          if (firstProject) handleCreateChat(firstProject.id, "Новая задача");
        }}
        onAdminClick={() => setShowAdmin(true)}
        onSimulate={activeChat === "c1" ? handleStartSimulation : undefined}
        onExportChat={handleExportChat}
        isDark={theme === "dark"}
        onToggleTheme={toggleTheme}
      />

      <div
        className={cn("h-screen flex overflow-hidden bg-[#F8F7F5] dark:bg-[#0a0c12]", isResizing && "select-none cursor-col-resize")}
      >
        {/* Left Sidebar */}
        <motion.div
          animate={{ width: sidebarCollapsed ? 56 : 240 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="shrink-0 h-full overflow-hidden"
        >
          <Sidebar
            activeChat={activeChat}
            onChatSelect={handleChatSelect}
            onAdminClick={() => setShowAdmin(true)}
            collapsed={sidebarCollapsed}
            onCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
            projects={projects}
            chats={allChats}
            onCreateProject={handleCreateProject}
            onCreateChat={handleCreateChat}
            onRenameChat={handleRenameChat}
            onDeleteChat={handleDeleteChat}
            onMoveChat={handleMoveChat}
            onRenameProject={handleRenameProject}
            onDeleteProject={handleDeleteProject}
            pinnedChats={pinnedChats}
            onPinChat={handlePinChat}
            onCommandPalette={() => setCommandPaletteOpen(true)}
            onPlaybooks={() => setShowPlaybooks(true)}
            onScheduled={() => setShowScheduled(true)}
            onSettingsClick={() => setShowSettings(true)}
            budgetExhausted={budgetExhausted}
            notifications={notifications}
            onMarkRead={handleMarkRead}
            onMarkAllRead={handleMarkAllRead}
            onDismissNotif={handleDismissNotif}
            onClearAllNotifs={handleClearAllNotifs}
          />
        </motion.div>

        {/* Center: Chat */}
        <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-[#0f1117] border-x border-[#E8E6E1] dark:border-[#2a2d3a]">
          <ChatHeader
            chatTitle={chat.title}
            projectName={projects.find(p => p.id === chat.projectId)?.name ?? "Проект"}
            status={headerStatus}
            rightPanelOpen={rightPanelOpen}
            onToggleRightPanel={() => setRightPanelOpen(!rightPanelOpen)}
            onSimulate={activeChat === "c1" ? handleStartSimulation : undefined}
            onReset={activeChat === "c1" ? handleResetSimulation : undefined}
            simState={activeChat === "c1" ? simState : "idle"}
            showSimButton={activeChat === "c1"}
            model={selectedModel}
            onModelChange={setSelectedModel}
            cost={chat.cost}
            duration={
              activeChat === "c1" && (simState === "running" || (simState === "done" && liveTime))
                ? liveTime
                : chat.duration
            }
            isTimerLive={activeChat === "c1" && simState === "running"}
            onCommandPalette={() => setCommandPaletteOpen(true)}
            isTakeover={isTakeover}
            onTakeoverActivate={() => { setIsTakeover(true); toast.info("Режим управления активирован — агент приостановлен"); }}
            onTakeoverDeactivate={() => { setIsTakeover(false); toast.success("Управление возвращено агенту"); }}
            isRunning={isRunning}
            onSimulateSSEDisconnect={simulateDisconnect}
            onSimulateSSEFailed={simulateFailed}
            onSimulateSSEOffline={simulateOffline}
          />

          {/* SSE Reconnecting Banner */}
          <AnimatePresence>
            {sseBannerVisible && (
              <SSEReconnectingBanner
                state={sseState}
                onRetry={retrySSE}
                onDismiss={() => setSSEBannerVisible(false)}
              />
            )}
          </AnimatePresence>

          {/* Takeover banner */}
          <AnimatePresence>
            {isTakeover && (
              <TakeoverBanner
                isActive={isTakeover}
                onActivate={() => setIsTakeover(true)}
                onDeactivate={() => { setIsTakeover(false); toast.success("Управление возвращено агенту"); }}
              />
            )}
          </AnimatePresence>

          {/* Chat messages area */}
          <div className="flex-1 overflow-y-auto px-4 py-6 space-y-5">
            <AnimatePresence mode="wait">
              {isLoadingChat ? (
                <SkeletonChat key="skeleton" />
              ) : (
                <motion.div
                  key={activeChat}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="space-y-5"
                >
                  {messages.length === 0 && simState === "idle" && (
                    <EmptyState onSend={handleSend} onSimulate={activeChat === "c1" ? handleStartSimulation : undefined} />
                  )}

                  <AnimatePresence initial={false}>
                    {messages.map((message, idx) => (
                      <ChatMessage
                        key={message.id}
                        message={message}
                        activeStep={activeStep}
                        onStepClick={handleStepClick}
                        isLast={idx === messages.length - 1}
                        isCompleted={simState === "done" || (activeChat !== "c1" && chat.status === "completed")}
                        onEdit={handleMessageEdit}
                        onArtifactOpen={handleArtifactOpen}
                      />
                    ))}
                  </AnimatePresence>

                  {/* Typing indicator */}
                  <AnimatePresence>
                    {showTypingIndicator && (
                      <motion.div
                        key="typing"
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -4 }}
                        transition={{ duration: 0.2 }}
                        className="flex gap-3"
                      >
                        <div className="w-7 h-7 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center shrink-0">
                          <Bot size={13} className="text-gray-600" />
                        </div>
                        <div className="flex items-center gap-3 px-4 py-3 bg-white border border-[#E8E6E1] rounded-2xl rounded-tl-sm shadow-sm">
                          <StatusBadge status="thinking" size="sm" />
                          <div className="flex gap-1">
                            {[0, 1, 2].map(i => (
                              <motion.span
                                key={i}
                                className="w-1.5 h-1.5 rounded-full bg-gray-300"
                                animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
                                transition={{ duration: 0.9, delay: i * 0.15, repeat: Infinity, ease: "easeInOut" }}
                              />
                            ))}
                          </div>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Live executing indicator for non-sim chats */}
                  {activeChat !== "c1" && (chat.status === "thinking" || chat.status === "executing" || chat.status === "searching") && (
                    <motion.div
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex gap-3"
                    >
                      <div className="w-7 h-7 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center shrink-0">
                        <Bot size={13} className="text-gray-600" />
                      </div>
                      <div className="flex items-center gap-3 px-4 py-3 bg-white border border-[#E8E6E1] rounded-2xl rounded-tl-sm shadow-sm">
                        <StatusBadge status={chat.status} size="sm" />
                        <div className="flex gap-1">
                          {[0, 1, 2].map(i => (
                            <motion.span
                              key={i}
                              className="w-1.5 h-1.5 rounded-full bg-gray-300"
                              animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
                              transition={{ duration: 0.9, delay: i * 0.15, repeat: Infinity, ease: "easeInOut" }}
                            />
                          ))}
                        </div>
                      </div>
                    </motion.div>
                  )}

                  <div ref={messagesEndRef} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Agent interrupt dialog */}
          <AnimatePresence>
            {interrupt && (
              <AgentInterruptDialog
                key="interrupt"
                question={interrupt.question}
                options={interrupt.options}
                onAnswer={handleAnswer}
                onDismiss={handleDismiss}
              />
            )}
          </AnimatePresence>

          {/* Plan footer */}
          {currentPlan.length > 0 && (
            <PlanFooter
              plan={currentPlan}
              completedCount={completedStepsCount}
              activeIndex={currentPlan.length > completedStepsCount ? completedStepsCount : undefined}
            />
          )}

          {/* Takeover terminal panel */}
          <AnimatePresence>
            {isTakeover && (
              <TakeoverPanel
                isActive={isTakeover}
                onSendCommand={(cmd) => toast.info(`Команда выполнена: ${cmd}`)}
              />
            )}
          </AnimatePresence>

          <Composer onSend={handleSend} budgetExhausted={budgetExhausted} onAdminRefill={handleAdminRefill} />
        </div>

        {/* Right Panel — resizable */}
        <AnimatePresence>
          {rightPanelOpen && (
            <motion.div
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: rightPanelWidth, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: isResizing ? 0 : 0.2, ease: "easeInOut" }}
              style={{ width: rightPanelWidth }}
              className="shrink-0 h-full overflow-hidden relative flex"
            >
              {/* Drag handle */}
              <div
                onMouseDown={handlePanelResize}
                className={cn(
                  "absolute left-0 top-0 bottom-0 w-1 cursor-col-resize z-10 group",
                  "hover:bg-indigo-400 transition-colors",
                  isResizing && "bg-indigo-500"
                )}
                title="Потяните чтобы изменить ширину"
              >
                <div className={cn(
                  "absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity",
                  isResizing && "opacity-100"
                )}>
                  {[0,1,2].map(i => (
                    <span key={i} className="w-1 h-1 rounded-full bg-indigo-400" />
                  ))}
                </div>
              </div>

              <div className="flex-1 overflow-hidden">
                <RightPanel
                  activeStep={activeStep}
                  onStepSelect={setActiveStep}
                  defaultTab={rightPanelTab}
                  steps={currentSteps}
                  plan={currentPlan}
                  completedSteps={completedStepsCount}
                  activeStepTitle={runningStep ? `Выполняется: ${runningStep.title}` : undefined}
                  isRunning={simState === "running"}
                  pendingArtifact={pendingArtifact}
                  onArtifactConsumed={() => setPendingArtifact(null)}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
}

// ─── Empty State ──────────────────────────────────────────────────────────────

function EmptyState({ onSend, onSimulate }: { onSend: (text: string) => void; onSimulate?: () => void }) {
  const suggestions = [
    "Установи Bitrix CMS на сервер",
    "Сделай SEO аудит сайта",
    "Настрой SSL сертификат",
    "Оптимизируй скорость загрузки",
  ];

  return (
    <div className="flex flex-col items-center justify-center h-full py-16 text-center">
      <div className="w-12 h-12 rounded-2xl bg-indigo-50 dark:bg-indigo-900/30 flex items-center justify-center mb-4">
        <Bot size={22} className="text-indigo-600" />
      </div>
      <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-1">Новый чат</h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6 max-w-xs">
        Поставьте задачу агенту или запустите симуляцию чтобы увидеть как работает ORION.
      </p>

      {onSimulate && (
        <button
          onClick={onSimulate}
          className="mb-5 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-all shadow-sm hover:shadow-md hover:-translate-y-0.5"
        >
          <span className="w-2 h-2 rounded-full bg-white/70 live-pulse" />
          Запустить симуляцию выполнения
        </button>
      )}

      <div className="grid grid-cols-2 gap-2 max-w-sm">
        {suggestions.map((s, i) => (
          <button
            key={i}
            onClick={() => onSend(s)}
            className="text-left px-3 py-2.5 rounded-lg border border-[#E8E6E1] dark:border-[#2a2d3a] bg-[#F8F7F5] dark:bg-[#1e2130] hover:bg-white dark:hover:bg-[#252840] hover:border-indigo-200 transition-all text-xs text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200"
          >
            {s}
          </button>
        ))}
      </div>

      <div className="mt-6 flex items-center gap-1.5 text-[11px] text-gray-400">
        <kbd className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-[#1e2130] border border-gray-200 dark:border-[#2a2d3a] text-[10px] font-mono">⌘K</kbd>
        <span>Палитра команд</span>
        <span className="mx-1">·</span>
        <kbd className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-[#1e2130] border border-gray-200 dark:border-[#2a2d3a] text-[10px] font-mono">⌘/</kbd>
        <span>Горячие клавиши</span>
      </div>
    </div>
  );
}
