// Design: "Warm Intelligence"
// Global Cmd+K command palette — quick actions, chat navigation, keyboard shortcuts

import { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  Command, CommandDialog, CommandEmpty, CommandGroup,
  CommandInput, CommandItem, CommandList, CommandSeparator, CommandShortcut,
} from "@/components/ui/command";
import {
  MessageSquare, Plus, Search, Settings, LayoutDashboard,
  Keyboard, Play, Download, Moon, Sun, Zap, Gauge, Sparkles, Crown,
  FolderOpen, Bot, ArrowRight,
} from "lucide-react";
import type { Chat, Project } from "@/lib/mockData";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  chats: Chat[];
  projects: Project[];
  activeChat: string;
  onChatSelect: (id: string) => void;
  onCreateChat: () => void;
  onAdminClick: () => void;
  onSimulate?: () => void;
  onExportChat?: () => void;
  isDark?: boolean;
  onToggleTheme?: () => void;
}

const SHORTCUTS = [
  { keys: ["⌘", "K"], label: "Открыть палитру команд" },
  { keys: ["⌘", "B"], label: "Свернуть/развернуть сайдбар" },
  { keys: ["⌘", "Enter"], label: "Отправить сообщение" },
  { keys: ["⌘", "\\"], label: "Открыть/закрыть панель деталей" },
  { keys: ["Esc"], label: "Остановить задачу / закрыть" },
  { keys: ["⌘", "E"], label: "Экспортировать чат" },
  { keys: ["⌘", "N"], label: "Новая задача" },
  { keys: ["⌘", "/"], label: "Показать горячие клавиши" },
];

export function CommandPalette({
  open, onOpenChange, chats, projects, activeChat,
  onChatSelect, onCreateChat, onAdminClick, onSimulate, onExportChat,
  isDark, onToggleTheme,
}: CommandPaletteProps) {
  const [showShortcuts, setShowShortcuts] = useState(false);

  const runAndClose = useCallback((fn: () => void) => {
    fn();
    onOpenChange(false);
  }, [onOpenChange]);

  const getProjectName = (projectId: string) =>
    projects.find(p => p.id === projectId)?.name ?? "Проект";

  return (
    <>
      <CommandDialog
        open={open}
        onOpenChange={onOpenChange}
        title="Палитра команд"
        description="Быстрый доступ ко всем функциям ORION"
      >
        <CommandInput placeholder="Поиск команд и чатов..." />
        <CommandList>
          <CommandEmpty>Ничего не найдено</CommandEmpty>

          {/* Quick actions */}
          <CommandGroup heading="Действия">
            <CommandItem onSelect={() => runAndClose(onCreateChat)}>
              <Plus size={14} className="mr-2 text-indigo-500" />
              Новая задача
              <CommandShortcut>⌘N</CommandShortcut>
            </CommandItem>
            {onSimulate && (
              <CommandItem onSelect={() => runAndClose(onSimulate)}>
                <Play size={14} className="mr-2 text-green-500" />
                Запустить симуляцию
              </CommandItem>
            )}
            {onExportChat && (
              <CommandItem onSelect={() => runAndClose(onExportChat)}>
                <Download size={14} className="mr-2 text-gray-500" />
                Экспортировать чат в Markdown
                <CommandShortcut>⌘E</CommandShortcut>
              </CommandItem>
            )}
            <CommandItem onSelect={() => runAndClose(onAdminClick)}>
              <LayoutDashboard size={14} className="mr-2 text-purple-500" />
              Открыть Админку
            </CommandItem>
            {onToggleTheme && (
              <CommandItem onSelect={() => runAndClose(onToggleTheme)}>
                {isDark
                  ? <Sun size={14} className="mr-2 text-amber-500" />
                  : <Moon size={14} className="mr-2 text-indigo-500" />
                }
                {isDark ? "Светлая тема" : "Тёмная тема"}
              </CommandItem>
            )}
            <CommandItem onSelect={() => { setShowShortcuts(true); onOpenChange(false); }}>
              <Keyboard size={14} className="mr-2 text-gray-500" />
              Горячие клавиши
              <CommandShortcut>⌘/</CommandShortcut>
            </CommandItem>
          </CommandGroup>

          <CommandSeparator />

          {/* Models */}
          <CommandGroup heading="Модель агента">
            {[
              { key: "mini", label: "Быстрый — GPT-5.4 Mini", icon: <Zap size={12} className="text-amber-500" /> },
              { key: "standard", label: "Стандарт — GPT-5.4", icon: <Gauge size={12} className="text-blue-500" /> },
              { key: "sonnet", label: "Про — Claude Sonnet 4.6", icon: <Sparkles size={12} className="text-violet-500" /> },
              { key: "opus", label: "Премиум — Claude Opus 4", icon: <Crown size={12} className="text-rose-500" /> },
            ].map(m => (
              <CommandItem key={m.key} onSelect={() => onOpenChange(false)}>
                <span className="mr-2">{m.icon}</span>
                {m.label}
              </CommandItem>
            ))}
          </CommandGroup>

          <CommandSeparator />

          {/* Chats */}
          <CommandGroup heading="Чаты">
            {chats.map(chat => (
              <CommandItem
                key={chat.id}
                onSelect={() => runAndClose(() => onChatSelect(chat.id))}
                className={cn(chat.id === activeChat && "bg-indigo-50")}
              >
                <MessageSquare size={13} className="mr-2 text-gray-400" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm truncate">{chat.title}</span>
                  <span className="ml-2 text-xs text-gray-400">{getProjectName(chat.projectId)}</span>
                </div>
                {chat.id === activeChat && <ArrowRight size={12} className="text-indigo-400 shrink-0" />}
              </CommandItem>
            ))}
          </CommandGroup>

          <CommandSeparator />

          {/* Projects */}
          <CommandGroup heading="Проекты">
            {projects.map(project => (
              <CommandItem key={project.id} onSelect={() => onOpenChange(false)}>
                <FolderOpen size={13} className="mr-2 text-gray-400" />
                {project.name}
                <span className="ml-auto text-xs text-gray-400">{chats.filter(c => c.projectId === project.id).length} задач</span>
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </CommandDialog>

      {/* Keyboard shortcuts modal */}
      <KeyboardShortcutsModal open={showShortcuts} onClose={() => setShowShortcuts(false)} />
    </>
  );
}

// ─── Keyboard Shortcuts Modal ─────────────────────────────────────────────────

function KeyboardShortcutsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl border border-[#E8E6E1] w-full max-w-md mx-4 overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#E8E6E1]">
          <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center">
            <Keyboard size={16} className="text-indigo-600" />
          </div>
          <div>
            <div className="text-sm font-semibold text-gray-900">Горячие клавиши</div>
            <div className="text-xs text-gray-500">ORION keyboard shortcuts</div>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors text-xs">
            Esc
          </button>
        </div>
        <div className="p-5 space-y-2">
          {SHORTCUTS.map((s, i) => (
            <div key={i} className="flex items-center justify-between py-1.5">
              <span className="text-sm text-gray-600">{s.label}</span>
              <div className="flex items-center gap-1">
                {s.keys.map((k, j) => (
                  <kbd key={j} className="px-2 py-0.5 rounded bg-gray-100 border border-gray-200 text-xs font-mono text-gray-700">
                    {k}
                  </kbd>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="px-5 py-3 border-t border-[#E8E6E1] bg-gray-50">
          <span className="text-xs text-gray-400">На Mac используйте ⌘, на Windows — Ctrl</span>
        </div>
      </div>
    </div>
  );
}
