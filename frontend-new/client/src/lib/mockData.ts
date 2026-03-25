// ORION UI Prototype — Mock Data
// Design: "Warm Intelligence" — warm off-white, indigo accent

export type AgentStatus =
  | "idle"
  | "thinking"
  | "executing"
  | "searching"
  | "verifying"
  | "waiting"
  | "completed"
  | "failed"
  | "partial"
  | "needs_review";

export type StepStatus =
  | "queued"
  | "running"
  | "success"
  | "failed"
  | "warning"
  | "skipped"
  | "partial";

export interface Project {
  id: string;
  name: string;
  type: string;
  chatCount: number;
  lastActivity: string;
  color: string;
}

export interface Chat {
  id: string;
  projectId: string;
  title: string;
  mode: "fast" | "standard" | "premium";
  status: AgentStatus;
  cost: number;
  duration: string; // e.g. "4m 32s" or "running"
  lastMessage: string;
  timestamp: string;
  model: string;
}

export interface Step {
  id: string;
  title: string;
  status: StepStatus;
  tool: string;
  startTime: string;
  duration: string;
  summary: string;
  args?: Record<string, string>;
  result?: string;
  verifier?: string;
  warning?: string;
  goldenPath?: boolean;
}

// Artifact for the ArtifactViewer component (rich preview/edit)
export interface ViewerArtifact {
  id: string;
  title: string;
  type: "html" | "code" | "markdown" | "image" | "diff";
  language?: string;
  content: string;
  originalContent?: string;
  createdAt: string;
  size?: string;
}

export interface Message {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  timestamp: string;
  steps?: Step[];
  plan?: string[];
  artifact?: Artifact;
  viewerArtifacts?: ViewerArtifact[];
  // Task progress tracking
  taskPlan?: { name: string; status: "pending" | "running" | "done" | "failed" }[];
  currentTool?: string;
  isStreaming?: boolean;
  thinkingContent?: string;
}

export interface Artifact {
  id: string;
  name: string;
  type: "code" | "report" | "site" | "image" | "document" | "html" | "pdf" | "spreadsheet" | "file";
  url?: string;
  download_url?: string;
  preview_url?: string;
  preview?: string;
  size?: string;
  createdAt: string;
}

export interface LogEntry {
  id: string;
  time: string;
  level: "info" | "warn" | "error" | "tool" | "verifier" | "judge";
  message: string;
}

// ─── Projects ───────────────────────────────────────────────────────────────

export const PROJECTS: Project[] = [
  { id: "p1", name: "Bitrix Landing", type: "Website", chatCount: 7, lastActivity: "2 мин назад", color: "#4F46E5" },
  { id: "p2", name: "WordPress Studio", type: "CMS", chatCount: 3, lastActivity: "1 час назад", color: "#D97706" },
  { id: "p3", name: "Dream Avto", type: "Website", chatCount: 12, lastActivity: "вчера", color: "#059669" },
  { id: "p4", name: "BlacksArt SEO", type: "SEO", chatCount: 5, lastActivity: "3 дня назад", color: "#7C3AED" },
  { id: "p5", name: "Orion Audit", type: "Internal", chatCount: 2, lastActivity: "неделю назад", color: "#DC2626" },
];

// ─── Chats ───────────────────────────────────────────────────────────────────

export const CHATS: Chat[] = [
  {
    id: "c1",
    projectId: "p1",
    title: "Установка Bitrix на сервер",
    mode: "premium",
    status: "executing",
    cost: 1.24,
    duration: "4m 12s",
    lastMessage: "Проверяю установку модулей...",
    timestamp: "14:32",
    model: "GPT-4o + Claude 3.5",
  },
  {
    id: "c2",
    projectId: "p1",
    title: "Настройка SSL сертификата",
    mode: "standard",
    status: "completed",
    cost: 0.38,
    duration: "2m 45s",
    lastMessage: "SSL успешно настроен, сайт доступен по HTTPS.",
    timestamp: "11:15",
    model: "GPT-4o",
  },
  {
    id: "c3",
    projectId: "p1",
    title: "Оптимизация скорости загрузки",
    mode: "fast",
    status: "failed",
    cost: 0.12,
    duration: "1m 03s",
    lastMessage: "Ошибка: не удалось подключиться к Redis.",
    timestamp: "вчера",
    model: "GPT-4o mini",
  },
  {
    id: "c4",
    projectId: "p2",
    title: "Миграция на новый хостинг",
    mode: "premium",
    status: "thinking",
    cost: 0.67,
    duration: "6m 20s",
    lastMessage: "Анализирую структуру базы данных...",
    timestamp: "13:48",
    model: "GPT-4o + Claude 3.5",
  },
  {
    id: "c5",
    projectId: "p1",
    title: "Настройка резервного копирования",
    mode: "standard",
    status: "needs_review",
    cost: 0.54,
    duration: "3m 18s",
    lastMessage: "Скрипт создан, но требует подтверждения расписания cron.",
    timestamp: "10:05",
    model: "GPT-5.4",
  },
];

// ─── Steps ───────────────────────────────────────────────────────────────────

export const STEPS: Step[] = [
  {
    id: "s1",
    title: "Проверил сервер",
    status: "success",
    tool: "SSH",
    startTime: "14:28:03",
    duration: "2.1s",
    summary: "Подключился по SSH, проверил версию PHP и доступные модули.",
    args: { host: "185.22.xx.xx", command: "php -v && php -m" },
    result: "PHP 8.2.10, модули: curl, gd, mbstring, mysqli ✓",
    goldenPath: true,
  },
  {
    id: "s2",
    title: "Сделал web search",
    status: "success",
    tool: "Browser",
    startTime: "14:28:06",
    duration: "1.4s",
    summary: "Поиск актуальной версии Bitrix и требований к серверу.",
    args: { query: "Bitrix CMS 2024 server requirements PHP 8.2" },
    result: "Найдено: Bitrix 23.x поддерживает PHP 8.2, требует MySQL 8+",
  },
  {
    id: "s3",
    title: "Открыл bitrixsetup.php",
    status: "success",
    tool: "Browser",
    startTime: "14:28:09",
    duration: "3.2s",
    summary: "Загрузил установочный скрипт и открыл в браузере.",
    args: { url: "http://185.22.xx.xx/bitrixsetup.php" },
    result: "Страница установки загружена, все проверки пройдены",
  },
  {
    id: "s4",
    title: "Установил зависимости",
    status: "success",
    tool: "Terminal",
    startTime: "14:29:15",
    duration: "45.3s",
    summary: "Установил необходимые PHP-расширения и настроил php.ini.",
    args: { command: "apt-get install php8.2-gd php8.2-curl php8.2-mbstring" },
    result: "Все зависимости установлены успешно",
    goldenPath: true,
  },
  {
    id: "s5",
    title: "Проверяю админку",
    status: "running",
    tool: "Browser",
    startTime: "14:32:41",
    duration: "...",
    summary: "Открываю административную панель Bitrix для финальной проверки.",
    args: { url: "http://185.22.xx.xx/bitrix/admin/" },
  },
];

// ─── Messages ────────────────────────────────────────────────────────────────

export const MESSAGES: Message[] = [
  {
    id: "m1",
    role: "user",
    content: "Установи Bitrix CMS на сервер 185.22.xx.xx. Доступ по SSH есть. Нужно полностью рабочее окружение с настроенной базой данных и SSL.",
    timestamp: "14:27",
  },
  {
    id: "m2",
    role: "agent",
    content: "Понял задачу. Начинаю установку Bitrix CMS на сервер. Сначала проверю текущее состояние сервера, затем установлю все необходимые компоненты.",
    timestamp: "14:27",
    plan: [
      "Проверить состояние сервера и версию PHP",
      "Загрузить и запустить установщик Bitrix",
      "Настроить базу данных MySQL",
      "Завершить установку через веб-интерфейс",
      "Настроить SSL сертификат",
      "Проверить работу через verifier",
    ],
    steps: [
      STEPS[0],
      STEPS[1],
      STEPS[2],
      STEPS[3],
    ],
  },
  {
    id: "m3",
    role: "system",
    content: "Агент выполняет задачу. Шаг 5 из 6: Проверка административной панели.",
    timestamp: "14:32",
  },
];

// ─── Logs ────────────────────────────────────────────────────────────────────

export const LOGS: LogEntry[] = [
  { id: "l1", time: "14:28:03", level: "info", message: "SSH connection established to 185.22.xx.xx" },
  { id: "l2", time: "14:28:04", level: "tool", message: "[SSH] php -v → PHP 8.2.10 (cli)" },
  { id: "l3", time: "14:28:06", level: "tool", message: "[Browser] search: 'Bitrix CMS 2024 server requirements'" },
  { id: "l4", time: "14:28:07", level: "info", message: "Golden path matched: bitrix-standard-install-v2" },
  { id: "l5", time: "14:28:09", level: "tool", message: "[Browser] navigate: http://185.22.xx.xx/bitrixsetup.php" },
  { id: "l6", time: "14:28:12", level: "verifier", message: "Pre-check: PHP version ✓, MySQL ✓, disk space ✓" },
  { id: "l7", time: "14:29:15", level: "tool", message: "[Terminal] apt-get install php8.2-gd php8.2-curl php8.2-mbstring php8.2-zip" },
  { id: "l8", time: "14:30:01", level: "info", message: "Dependencies installed successfully" },
  { id: "l9", time: "14:30:45", level: "tool", message: "[SSH] wget https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php" },
  { id: "l10", time: "14:31:22", level: "verifier", message: "Bitrix installer checksum verified ✓" },
  { id: "l11", time: "14:32:41", level: "tool", message: "[Browser] navigate: http://185.22.xx.xx/bitrix/admin/" },
  { id: "l12", time: "14:32:42", level: "info", message: "Waiting for admin panel to load..." },
];

// ─── Artifacts ───────────────────────────────────────────────────────────────

export const ARTIFACTS: Artifact[] = [
  {
    id: "a1",
    name: "install_log.txt",
    type: "document",
    size: "12 KB",
    createdAt: "14:30",
    preview: "Installation log for Bitrix CMS setup...",
  },
  {
    id: "a2",
    name: "server_config.sh",
    type: "code",
    size: "3.2 KB",
    createdAt: "14:29",
    preview: "#!/bin/bash\n# Server configuration script\napt-get update...",
  },
  {
    id: "a3",
    name: "nginx.conf",
    type: "code",
    size: "1.8 KB",
    createdAt: "14:31",
    preview: "server {\n    listen 443 ssl;\n    server_name example.com;",
  },
  {
    id: "a4",
    name: "screenshot_admin.png",
    type: "image",
    size: "245 KB",
    createdAt: "14:32",
  },
];

// ─── Admin Dashboard ─────────────────────────────────────────────────────────

export const ADMIN_STATS = {
  totalUsers: 24,
  activeTasks: 7,
  successRate: 87.4,
  failRate: 5.2,
  totalCost: 142.80,
  avgTaskTime: "4m 32s",
  verifierRejects: 12,
  judgeRejects: 4,
};

export const ADMIN_USERS = [
  { id: "u1", name: "Алексей Петров", email: "alex@company.ru", role: "admin", tasks: 45, cost: 38.20, lastActive: "сейчас" },
  { id: "u2", name: "Мария Сидорова", email: "maria@company.ru", role: "user", tasks: 23, cost: 19.40, lastActive: "1 час назад" },
  { id: "u3", name: "Дмитрий Козлов", email: "dmitry@company.ru", role: "user", tasks: 67, cost: 54.10, lastActive: "вчера" },
  { id: "u4", name: "Анна Новикова", email: "anna@company.ru", role: "user", tasks: 12, cost: 8.90, lastActive: "3 дня назад" },
  { id: "u5", name: "Сергей Волков", email: "sergey@company.ru", role: "manager", tasks: 31, cost: 22.20, lastActive: "неделю назад" },
];

export const ADMIN_TASKS = [
  { id: "t1", title: "Установка Bitrix на сервер", user: "Алексей Петров", status: "executing", cost: 1.24, duration: "4m 12s", model: "GPT-4o + Claude" },
  { id: "t2", title: "Настройка SSL сертификата", user: "Мария Сидорова", status: "completed", cost: 0.38, duration: "2m 45s", model: "GPT-4o" },
  { id: "t3", title: "Миграция WordPress", user: "Дмитрий Козлов", status: "thinking", cost: 0.67, duration: "6m 30s", model: "GPT-4o + Claude" },
  { id: "t4", title: "SEO аудит сайта", user: "Анна Новикова", status: "failed", cost: 0.12, duration: "1m 20s", model: "GPT-4o mini" },
  { id: "t5", title: "Оптимизация базы данных", user: "Сергей Волков", status: "completed", cost: 0.89, duration: "8m 15s", model: "GPT-4o" },
  { id: "t6", title: "Настройка резервного копирования", user: "Алексей Петров", status: "needs_review", cost: 0.54, duration: "3m 18s", model: "GPT-5.4" },
];

export const GOLDEN_PATHS = [
  { id: "gp1", name: "bitrix-standard-install-v2", uses: 34, successRate: 94, lastUsed: "2 мин назад" },
  { id: "gp2", name: "ssl-letsencrypt-nginx", uses: 28, successRate: 98, lastUsed: "1 час назад" },
  { id: "gp3", name: "wordpress-migration-v3", uses: 19, successRate: 89, lastUsed: "вчера" },
  { id: "gp4", name: "mysql-optimization-basic", uses: 12, successRate: 91, lastUsed: "3 дня назад" },
];
