// Design: "Warm Intelligence"
// Playbooks — saved reusable agent workflows (like Devin Playbooks / Golden Paths)

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import {
  BookOpen, Plus, Play, Star, Clock, ChevronRight, Search,
  Tag, Copy, Pencil, Trash2, X, Check, Zap, Globe, Database,
  Shield, Code2, Server, Package
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";

interface Playbook {
  id: string;
  title: string;
  description: string;
  category: string;
  steps: number;
  avgTime: string;
  avgCost: string;
  usedCount: number;
  starred: boolean;
  tags: string[];
  icon: React.ReactNode;
  prompt: string;
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  "Деплой":      <Server size={12} className="text-blue-500" />,
  "SEO":         <Globe size={12} className="text-green-500" />,
  "Безопасность": <Shield size={12} className="text-red-500" />,
  "База данных": <Database size={12} className="text-amber-500" />,
  "Разработка":  <Code2 size={12} className="text-purple-500" />,
  "Зависимости": <Package size={12} className="text-indigo-500" />,
};

const PLAYBOOKS: Playbook[] = [
  {
    id: "pb1",
    title: "Установка Bitrix CMS",
    description: "Полная установка 1С-Битрикс: скачивание, настройка БД, nginx, PHP, SSL",
    category: "Деплой",
    steps: 12,
    avgTime: "4:30",
    avgCost: "$1.20",
    usedCount: 23,
    starred: true,
    tags: ["bitrix", "cms", "nginx", "php"],
    icon: <Server size={14} className="text-blue-500" />,
    prompt: "Установи Bitrix CMS на сервер. Настрой nginx, PHP 8.2, MySQL 8.0, SSL сертификат.",
  },
  {
    id: "pb2",
    title: "SSL сертификат Let's Encrypt",
    description: "Получение и настройка бесплатного SSL, автообновление через certbot",
    category: "Безопасность",
    steps: 4,
    avgTime: "1:15",
    avgCost: "$0.18",
    usedCount: 41,
    starred: true,
    tags: ["ssl", "letsencrypt", "certbot", "nginx"],
    icon: <Shield size={14} className="text-green-500" />,
    prompt: "Настрой SSL сертификат Let's Encrypt для домена. Настрой автообновление через certbot.",
  },
  {
    id: "pb3",
    title: "SEO аудит сайта",
    description: "Полный технический SEO аудит: скорость, мета-теги, sitemap, robots.txt",
    category: "SEO",
    steps: 8,
    avgTime: "3:00",
    avgCost: "$0.85",
    usedCount: 17,
    starred: false,
    tags: ["seo", "audit", "pagespeed", "sitemap"],
    icon: <Globe size={14} className="text-green-500" />,
    prompt: "Проведи полный SEO аудит сайта. Проверь скорость, мета-теги, sitemap, robots.txt, структуру заголовков.",
  },
  {
    id: "pb4",
    title: "Настройка Redis кэширования",
    description: "Установка Redis, настройка кэширования для PHP/Bitrix, мониторинг",
    category: "База данных",
    steps: 6,
    avgTime: "2:00",
    avgCost: "$0.55",
    usedCount: 9,
    starred: false,
    tags: ["redis", "cache", "performance"],
    icon: <Database size={14} className="text-amber-500" />,
    prompt: "Установи и настрой Redis для кэширования. Подключи к PHP приложению, настрой мониторинг.",
  },
  {
    id: "pb5",
    title: "Обновление зависимостей",
    description: "Безопасное обновление npm/composer пакетов с проверкой совместимости",
    category: "Зависимости",
    steps: 5,
    avgTime: "1:45",
    avgCost: "$0.40",
    usedCount: 34,
    starred: false,
    tags: ["npm", "composer", "update", "security"],
    icon: <Package size={14} className="text-indigo-500" />,
    prompt: "Обнови все зависимости проекта. Проверь совместимость, запусти тесты, зафиксируй изменения.",
  },
  {
    id: "pb6",
    title: "Настройка CI/CD пайплайна",
    description: "GitHub Actions: автодеплой, тесты, нотификации в Telegram",
    category: "Разработка",
    steps: 9,
    avgTime: "5:00",
    avgCost: "$1.50",
    usedCount: 6,
    starred: false,
    tags: ["github", "ci/cd", "deploy", "telegram"],
    icon: <Code2 size={14} className="text-purple-500" />,
    prompt: "Настрой CI/CD пайплайн через GitHub Actions. Автодеплой на сервер, запуск тестов, уведомления в Telegram.",
  },
];

interface PlaybooksPanelProps {
  onRunPlaybook: (prompt: string, title: string) => void;
  onClose?: () => void;
}

export function PlaybooksPanel({ onRunPlaybook, onClose }: PlaybooksPanelProps) {
  const [search, setSearch] = useState("");

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onClose) onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [playbooks, setPlaybooks] = useState(PLAYBOOKS);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const categories = Array.from(new Set(PLAYBOOKS.map(p => p.category)));

  const filtered = playbooks.filter(p => {
    const matchSearch = !search || p.title.toLowerCase().includes(search.toLowerCase()) ||
      p.description.toLowerCase().includes(search.toLowerCase()) ||
      p.tags.some(t => t.includes(search.toLowerCase()));
    const matchCategory = !selectedCategory || p.category === selectedCategory;
    return matchSearch && matchCategory;
  });

  const starred = filtered.filter(p => p.starred);
  const rest = filtered.filter(p => !p.starred);

  const toggleStar = (id: string) => {
    setPlaybooks(prev => prev.map(p => p.id === id ? { ...p, starred: !p.starred } : p));
  };

  const handleRun = (pb: Playbook) => {
    onRunPlaybook(pb.prompt, pb.title);
    toast.success(`Плейбук «${pb.title}» запущен`);
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-[#E8E6E1] shrink-0">
        <BookOpen size={14} className="text-indigo-500" />
        <span className="text-sm font-semibold text-gray-800 flex-1">Плейбуки</span>
        <button
          onClick={() => toast.info("Создание плейбука — скоро")}
          className="flex items-center gap-1 px-2 py-1 rounded-md bg-indigo-50 text-indigo-600 text-xs font-medium hover:bg-indigo-100 transition-colors"
        >
          <Plus size={11} />
          Новый
        </button>
        {onClose && (
          <button onClick={onClose} className="p-1 rounded text-gray-400 hover:text-gray-600 transition-colors">
            <X size={13} />
          </button>
        )}
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-[#E8E6E1] shrink-0">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск плейбуков..."
            className="w-full pl-7 pr-3 py-1.5 text-xs bg-[#F8F7F5] border border-[#E8E6E1] rounded-lg text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-300"
          />
        </div>
        {/* Category filters */}
        <div className="flex gap-1.5 mt-2 flex-wrap">
          <button
            onClick={() => setSelectedCategory(null)}
            className={cn(
              "px-2 py-0.5 rounded-full text-[10px] font-medium transition-colors",
              !selectedCategory ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-500 hover:bg-gray-200"
            )}
          >
            Все
          </button>
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat === selectedCategory ? null : cat)}
              className={cn(
                "flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium transition-colors",
                selectedCategory === cat ? "bg-indigo-100 text-indigo-700" : "bg-gray-100 text-gray-500 hover:bg-gray-200"
              )}
            >
              {CATEGORY_ICONS[cat]}
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {starred.length > 0 && (
          <div>
            <div className="flex items-center gap-1 mb-1.5">
              <Star size={10} className="text-amber-400 fill-amber-400" />
              <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Избранные</span>
            </div>
            <div className="space-y-1.5">
              {starred.map(pb => (
                <PlaybookCard
                  key={pb.id}
                  playbook={pb}
                  expanded={expandedId === pb.id}
                  onExpand={() => setExpandedId(expandedId === pb.id ? null : pb.id)}
                  onRun={() => handleRun(pb)}
                  onStar={() => toggleStar(pb.id)}
                />
              ))}
            </div>
          </div>
        )}

        {rest.length > 0 && (
          <div>
            {starred.length > 0 && (
              <div className="flex items-center gap-1 mb-1.5 mt-2">
                <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Все плейбуки</span>
              </div>
            )}
            <div className="space-y-1.5">
              {rest.map(pb => (
                <PlaybookCard
                  key={pb.id}
                  playbook={pb}
                  expanded={expandedId === pb.id}
                  onExpand={() => setExpandedId(expandedId === pb.id ? null : pb.id)}
                  onRun={() => handleRun(pb)}
                  onStar={() => toggleStar(pb.id)}
                />
              ))}
            </div>
          </div>
        )}

        {filtered.length === 0 && (
          <div className="text-center py-8 text-xs text-gray-400">
            <BookOpen size={24} className="mx-auto mb-2 opacity-30" />
            Плейбуки не найдены
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Playbook Card ────────────────────────────────────────────────────────────

function PlaybookCard({ playbook: pb, expanded, onExpand, onRun, onStar }: {
  playbook: Playbook;
  expanded: boolean;
  onExpand: () => void;
  onRun: () => void;
  onStar: () => void;
}) {
  return (
    <motion.div
      layout
      className="rounded-xl border border-[#E8E6E1] bg-white overflow-hidden hover:border-indigo-200 transition-colors"
    >
      <div className="flex items-start gap-2.5 px-3 py-2.5 cursor-pointer" onClick={onExpand}>
        <div className="w-7 h-7 rounded-lg bg-gray-50 border border-[#E8E6E1] flex items-center justify-center shrink-0 mt-0.5">
          {pb.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-semibold text-gray-800 truncate">{pb.title}</span>
            <span className="shrink-0 text-[9px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500">{pb.category}</span>
          </div>
          <div className="text-[10px] text-gray-500 mt-0.5 line-clamp-1">{pb.description}</div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-[10px] text-gray-400">{pb.steps} шагов</span>
            <span className="text-[10px] text-gray-400">~{pb.avgTime}</span>
            <span className="text-[10px] text-gray-400 font-mono">{pb.avgCost}</span>
            <span className="text-[10px] text-gray-400">{pb.usedCount}x</span>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={e => { e.stopPropagation(); onStar(); }}
            className="p-1 rounded hover:bg-gray-100 transition-colors"
          >
            <Star size={11} className={cn(pb.starred ? "text-amber-400 fill-amber-400" : "text-gray-300")} />
          </button>
          <ChevronRight size={12} className={cn("text-gray-300 transition-transform", expanded && "rotate-90")} />
        </div>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-[#E8E6E1] pt-2.5 space-y-2.5">
              {/* Prompt preview */}
              <div className="bg-gray-50 rounded-lg px-3 py-2 text-[11px] text-gray-600 font-mono leading-relaxed">
                {pb.prompt}
              </div>
              {/* Tags */}
              <div className="flex gap-1.5 flex-wrap">
                {pb.tags.map(tag => (
                  <span key={tag} className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 text-[10px]">
                    #{tag}
                  </span>
                ))}
              </div>
              {/* Actions */}
              <div className="flex gap-2">
                <button
                  onClick={onRun}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 transition-colors"
                >
                  <Play size={11} />
                  Запустить
                </button>
                <button
                  onClick={() => { navigator.clipboard.writeText(pb.prompt); toast.success("Скопировано"); }}
                  className="px-3 py-2 rounded-lg border border-[#E8E6E1] text-gray-500 hover:bg-gray-50 transition-colors"
                  title="Скопировать промпт"
                >
                  <Copy size={12} />
                </button>
                <button
                  onClick={() => toast.info("Редактирование плейбука — скоро")}
                  className="px-3 py-2 rounded-lg border border-[#E8E6E1] text-gray-500 hover:bg-gray-50 transition-colors"
                  title="Редактировать"
                >
                  <Pencil size={12} />
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
