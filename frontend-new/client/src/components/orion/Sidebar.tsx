// ORION Sidebar — Manus-inspired clean design
// Features: create project (modal), create chat, context menu on chats, search, collapse

import { cn } from "@/lib/utils";
import { type Chat, type Project } from "@/lib/mockData";
import { Bot, Plus, Search, MessageSquare, LayoutDashboard,
  ChevronRight, ChevronDown, FolderOpen, MoreHorizontal,
  Pencil, Trash2, FolderInput, PanelLeftClose, PanelLeftOpen,
  BookOpen, Sun, Moon, Settings, AlertTriangle, Pin, PinOff, Calendar
} from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { useTheme } from "@/contexts/ThemeContext";
import { useCurrentUser, ROLE_COLORS } from "@/contexts/CurrentUserContext";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { NotificationCenter, type AppNotification } from "./NotificationCenter";

interface SidebarProps {
  activeChat: string;
  onChatSelect: (id: string) => void;
  onAdminClick: () => void;
  collapsed?: boolean;
  onCollapse?: () => void;
  // State lifted up so sidebar can create/rename/delete
  projects: Project[];
  chats: Chat[];
  onCreateProject: (name: string) => void;
  onCreateChat: (projectId: string, title: string) => void;
  onRenameChat: (chatId: string, title: string) => void;
  onDeleteChat: (chatId: string) => void;
  onMoveChat: (chatId: string, projectId: string) => void;
  onRenameProject: (projectId: string, name: string) => void;
  onDeleteProject: (projectId: string) => void;
  pinnedChats?: Set<string>;
  onPinChat?: (chatId: string) => void;
  onCommandPalette?: () => void;
  onPlaybooks?: () => void;
  onScheduled?: () => void;
  onSettingsClick?: () => void;
  budgetExhausted?: boolean;
  notifications?: AppNotification[];
  onMarkRead?: (id: string) => void;
  onMarkAllRead?: () => void;
  onDismissNotif?: (id: string) => void;
  onClearAllNotifs?: () => void;
}

export function Sidebar({
  activeChat, onChatSelect, onAdminClick,
  collapsed, onCollapse,
  projects, chats,
  onCreateProject, onCreateChat, onRenameChat, onDeleteChat, onMoveChat,
  onRenameProject, onDeleteProject,
  pinnedChats, onPinChat, onCommandPalette, onPlaybooks, onScheduled, onSettingsClick,
  budgetExhausted, notifications = [], onMarkRead, onMarkAllRead, onDismissNotif, onClearAllNotifs,
}: SidebarProps) {
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(new Set(["p1"]));
  const [searchQuery, setSearchQuery] = useState("");
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [renamingChat, setRenamingChat] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renamingProject, setRenamingProject] = useState<string | null>(null);
  const [renameProjectValue, setRenameProjectValue] = useState("");
  const createInputRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const renameProjectInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (showCreateProject) setTimeout(() => createInputRef.current?.focus(), 50);
  }, [showCreateProject]);

  useEffect(() => {
    if (renamingChat) setTimeout(() => renameInputRef.current?.focus(), 50);
  }, [renamingChat]);

  useEffect(() => {
    if (renamingProject) setTimeout(() => renameProjectInputRef.current?.focus(), 50);
  }, [renamingProject]);

  const handleRenameProjectSubmit = () => {
    if (renamingProject && renameProjectValue.trim()) {
      onRenameProject(renamingProject, renameProjectValue.trim());
    }
    setRenamingProject(null);
    setRenameProjectValue("");
  };

  const toggleProject = (id: string) => {
    setExpandedProjects(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleCreateProject = () => {
    const name = newProjectName.trim();
    if (!name) return;
    onCreateProject(name);
    setNewProjectName("");
    setShowCreateProject(false);
  };

  const handleRenameSubmit = () => {
    if (!renamingChat || !renameValue.trim()) { setRenamingChat(null); return; }
    onRenameChat(renamingChat, renameValue.trim());
    setRenamingChat(null);
  };

  const startRename = (chat: Chat) => {
    setRenamingChat(chat.id);
    setRenameValue(chat.title);
  };

  const filteredChats = searchQuery
    ? chats.filter(c => c.title.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];

  return (
    <aside className={cn(
      "flex flex-col h-full bg-[#F7F6F3] dark:bg-[#0f1117] border-r border-[#E8E6E1] dark:border-[#2a2d3a] transition-all duration-200 shrink-0",
      collapsed ? "w-12" : "w-56"
    )}>
      {/* Header */}
      <div className="flex items-center h-12 px-3 shrink-0">
        {!collapsed && (
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <div className="w-6 h-6 rounded-md bg-indigo-600 flex items-center justify-center shrink-0">
              <Bot size={13} className="text-white" />
            </div>
            <span className="font-semibold text-[14px] text-gray-900 dark:text-gray-100 tracking-tight">ORION</span>
          </div>
        )}
        {collapsed && (
          <div className="w-6 h-6 rounded-md bg-indigo-600 flex items-center justify-center mx-auto">
            <Bot size={13} className="text-white" />
          </div>
        )}
        {onCollapse && !collapsed && (
          <button
            onClick={onCollapse}
            className="p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 transition-colors shrink-0"
            title="Свернуть"
          >
            <PanelLeftClose size={14} />
          </button>
        )}
        {onCollapse && collapsed && (
          <button
            onClick={onCollapse}
            className="absolute left-0 right-0 flex justify-center mt-1"
            title="Развернуть"
          >
            <PanelLeftOpen size={14} className="text-gray-400" />
          </button>
        )}
      </div>

      {collapsed ? (
        // Collapsed state — just icons
        <div className="flex flex-col items-center gap-1 px-1.5 pt-1 flex-1">
          <button
            onClick={onCollapse}
            className="w-8 h-8 flex items-center justify-center rounded-md hover:bg-white transition-colors text-gray-500"
            title="Новый чат"
          >
            <Plus size={15} />
          </button>
          <button
            onClick={onAdminClick}
            className="w-8 h-8 flex items-center justify-center rounded-md hover:bg-white transition-colors text-gray-400"
            title="Админка"
          >
            <LayoutDashboard size={15} />
          </button>
        </div>
      ) : (
        <>
          {/* New task */}
          <div className="px-2 pb-1 shrink-0">
            <button
              onClick={() => {
                if (budgetExhausted) {
                  toast.error("Бюджет исчерпан. Обратитесь к администратору для пополнения.");
                  return;
                }
                // Create new chat in first project
                const firstProject = projects[0];
                if (firstProject) {
                  onCreateChat(firstProject.id, "Новая задача");
                  setExpandedProjects(prev => new Set(Array.from(prev).concat(firstProject.id)));
                }
              }}
              className={cn(
                "w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm transition-colors font-medium",
                budgetExhausted
                  ? "text-red-400 dark:text-red-500 cursor-not-allowed opacity-60"
                  : "text-gray-700 dark:text-gray-200 hover:bg-white dark:hover:bg-[#1e2130]"
              )}
            >
              {budgetExhausted ? <AlertTriangle size={14} className="text-red-400" /> : <Plus size={14} className="text-gray-500" />}
              {budgetExhausted ? "Бюджет исчерпан" : "Новая задача"}
            </button>
          </div>

          {/* Search */}
          <div className="px-2 pb-2 shrink-0">
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Поиск..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-7 pr-3 py-1.5 text-xs bg-white dark:bg-[#1e2130] border border-[#E8E6E1] dark:border-[#2a2d3a] rounded-md text-gray-700 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-300 focus:border-indigo-300"
              />
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-2">
            {searchQuery ? (
              // Search results
              <div>
                <div className="px-1 py-1 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                  Результаты
                </div>
                {filteredChats.length === 0 ? (
                  <div className="px-2 py-3 text-xs text-gray-400 text-center">Ничего не найдено</div>
                ) : filteredChats.map(chat => (
                  <ChatRow
                    key={chat.id}
                    chat={chat}
                    active={activeChat === chat.id}
                    renaming={renamingChat === chat.id}
                    renameValue={renameValue}
                    renameInputRef={renameInputRef}
                    onRenameChange={setRenameValue}
                    onRenameSubmit={handleRenameSubmit}
                    onClick={() => onChatSelect(chat.id)}
                    onRename={() => startRename(chat)}
                    onDelete={() => onDeleteChat(chat.id)}
                    onMove={(pid) => onMoveChat(chat.id, pid)}
                    projects={projects}
                  />
                ))}
              </div>
            ) : (
              // Projects tree
              <>
                {/* Pinned chats */}
                {pinnedChats && pinnedChats.size > 0 && (
                  <div className="mb-2">
                    <div className="flex items-center gap-1 px-1 py-1 mb-0.5">
                      <Pin size={10} className="text-gray-400" />
                      <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Закреплённые</span>
                    </div>
                    {chats.filter(c => pinnedChats.has(c.id)).map(chat => (
                      <ChatRow
                        key={`pinned-${chat.id}`}
                        chat={chat}
                        active={activeChat === chat.id}
                        renaming={renamingChat === chat.id}
                        renameValue={renameValue}
                        renameInputRef={renameInputRef}
                        onRenameChange={setRenameValue}
                        onRenameSubmit={handleRenameSubmit}
                        onClick={() => onChatSelect(chat.id)}
                        onRename={() => startRename(chat)}
                        onDelete={() => onDeleteChat(chat.id)}
                        onMove={(pid) => onMoveChat(chat.id, pid)}
                        projects={projects}
                        isPinned={true}
                        onPin={onPinChat ? () => onPinChat(chat.id) : undefined}
                      />
                    ))}
                    <div className="mt-1.5 border-b border-[#E8E6E1]" />
                  </div>
                )}

                <div className="flex items-center justify-between px-1 py-1 mb-0.5">
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Проекты</span>
                  <button
                    onClick={() => setShowCreateProject(true)}
                    className="p-0.5 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 transition-colors"
                    title="Создать проект"
                  >
                    <Plus size={12} />
                  </button>
                </div>

                {/* Create project inline */}
                {showCreateProject && (
                  <div className="mb-1 px-1">
                    <div className="flex items-center gap-1.5 bg-white border border-indigo-300 rounded-md px-2 py-1.5 shadow-sm">
                      <FolderOpen size={12} className="text-indigo-400 shrink-0" />
                      <input
                        ref={createInputRef}
                        type="text"
                        value={newProjectName}
                        onChange={e => setNewProjectName(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === "Enter") handleCreateProject();
                          if (e.key === "Escape") { setShowCreateProject(false); setNewProjectName(""); }
                        }}
                        placeholder="Название проекта..."
                        className="flex-1 text-xs bg-transparent focus:outline-none text-gray-800 placeholder-gray-400"
                      />
                      <button
                        onClick={handleCreateProject}
                        disabled={!newProjectName.trim()}
                        className="text-[10px] font-medium text-indigo-600 hover:text-indigo-800 disabled:text-gray-300 transition-colors"
                      >
                        OK
                      </button>
                    </div>
                    <div className="text-[10px] text-gray-400 mt-1 px-1">Enter — создать · Esc — отмена</div>
                  </div>
                )}

                {projects.map(project => (
                  <ProjectSection
                    key={project.id}
                    project={project}
                    expanded={expandedProjects.has(project.id)}
                    onToggle={() => toggleProject(project.id)}
                    chats={chats.filter(c => c.projectId === project.id)}
                    activeChat={activeChat}
                    renamingChat={renamingChat}
                    renameValue={renameValue}
                    renameInputRef={renameInputRef}
                    onRenameChange={setRenameValue}
                    onRenameSubmit={handleRenameSubmit}
                    onChatSelect={onChatSelect}
                    onCreateChat={() => {
                      onCreateChat(project.id, "Новая задача");
                      setExpandedProjects(prev => new Set(Array.from(prev).concat(project.id)));
                    }}
                    onRenameChat={startRename}
                    onDeleteChat={onDeleteChat}
                    onMoveChat={onMoveChat}
                    allProjects={projects}
                    renamingProject={renamingProject === project.id}
                    renameProjectValue={renameProjectValue}
                    renameProjectInputRef={renameProjectInputRef}
                    onRenameProjectChange={setRenameProjectValue}
                    onRenameProjectSubmit={handleRenameProjectSubmit}
                    onStartRenameProject={() => { setRenamingProject(project.id); setRenameProjectValue(project.name); }}
                    onDeleteProject={() => onDeleteProject(project.id)}
                    pinnedChats={pinnedChats}
                    onPinChat={onPinChat}
                  />
                ))}
              </>
            )}
          </div>

          {/* Bottom */}
          <div className="border-t border-[#E8E6E1] dark:border-[#2a2d3a] px-2 py-2 shrink-0 space-y-0.5">
            {onPlaybooks && (
              <button
                className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs text-gray-500 dark:text-gray-400 hover:bg-white dark:hover:bg-[#1e2130] hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                onClick={onPlaybooks}
              >
                <BookOpen size={13} />
                Плейбуки
              </button>
            )}
            {onScheduled && (
              <button
                className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs text-gray-500 dark:text-gray-400 hover:bg-white dark:hover:bg-[#1e2130] hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
                onClick={onScheduled}
              >
                <Calendar size={13} />
                Расписание
              </button>
            )}
            <button
              onClick={onAdminClick}
              className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs text-gray-500 dark:text-gray-400 hover:bg-white dark:hover:bg-[#1e2130] hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <LayoutDashboard size={13} />
              Админка
            </button>
            <ThemeToggleButton />
            <button
              className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs text-gray-500 dark:text-gray-400 hover:bg-white dark:hover:bg-[#1e2130] hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
              onClick={() => onSettingsClick?.()}
            >
              <Settings size={13} />
              Настройки
            </button>

            {/* User + Notifications */}
            <UserAvatarRow onSettingsClick={onSettingsClick} notifications={notifications} onMarkRead={onMarkRead} onMarkAllRead={onMarkAllRead} onDismissNotif={onDismissNotif} onClearAllNotifs={onClearAllNotifs} />
          </div>
        </>
      )}
    </aside>
  );
}

// ─── Theme Toggle ────────────────────────────────────────────────────────────

function ThemeToggleButton() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      onClick={toggleTheme}
      className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs text-gray-500 dark:text-gray-400 hover:bg-white dark:hover:bg-[#1e2130] hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
    >
      {isDark ? <Sun size={13} /> : <Moon size={13} />}
      {isDark ? "Светлая тема" : "Тёмная тема"}
    </button>
  );
}

// ─── Project Section ──────────────────────────────────────────────────────────

function ProjectSection({
  project, expanded, onToggle, chats, activeChat,
  renamingChat, renameValue, renameInputRef, onRenameChange, onRenameSubmit,
  onChatSelect, onCreateChat, onRenameChat, onDeleteChat, onMoveChat, allProjects,
  renamingProject, renameProjectValue, renameProjectInputRef,
  onRenameProjectChange, onRenameProjectSubmit, onStartRenameProject, onDeleteProject,
  pinnedChats, onPinChat,
}: {
  project: Project;
  expanded: boolean;
  onToggle: () => void;
  chats: Chat[];
  activeChat: string;
  renamingChat: string | null;
  renameValue: string;
  renameInputRef: React.RefObject<HTMLInputElement | null>;
  onRenameChange: (v: string) => void;
  onRenameSubmit: () => void;
  onChatSelect: (id: string) => void;
  onCreateChat: () => void;
  onRenameChat: (chat: Chat) => void;
  onDeleteChat: (id: string) => void;
  onMoveChat: (chatId: string, projectId: string) => void;
  allProjects: Project[];
  renamingProject: boolean;
  renameProjectValue: string;
  renameProjectInputRef: React.RefObject<HTMLInputElement | null>;
  onRenameProjectChange: (v: string) => void;
  onRenameProjectSubmit: () => void;
  onStartRenameProject: () => void;
  onDeleteProject: () => void;
  pinnedChats?: Set<string>;
  onPinChat?: (chatId: string) => void;
}) {
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const totalCost = chats.reduce((sum, c) => sum + c.cost, 0);

  return (
    <div className="mb-0.5">
      {renamingProject ? (
        <div className="flex items-center gap-1.5 px-1 py-1 rounded-md bg-white border border-indigo-300 mb-0.5">
          <FolderOpen size={12} className="text-indigo-400 shrink-0" />
          <input
            ref={renameProjectInputRef}
            type="text"
            value={renameProjectValue}
            onChange={e => onRenameProjectChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter") onRenameProjectSubmit();
              if (e.key === "Escape") onRenameProjectSubmit();
            }}
            onBlur={onRenameProjectSubmit}
            className="flex-1 text-xs bg-transparent focus:outline-none text-gray-800"
          />
        </div>
      ) : (
      <div className="group flex items-center gap-1.5 px-1 py-1 rounded-md hover:bg-white dark:hover:bg-[#1e2130] transition-colors">
        <button onClick={onToggle} className="flex items-center gap-1.5 flex-1 min-w-0 text-left">
          <FolderOpen size={13} className="text-gray-400 shrink-0" />
          <span className="flex-1 text-xs font-medium text-gray-700 dark:text-gray-300 truncate">{project.name}</span>
          {totalCost > 0 && (
            <span className="text-[10px] text-gray-400 font-mono shrink-0">${totalCost.toFixed(2)}</span>
          )}
          {expanded
            ? <ChevronDown size={11} className="text-gray-400 shrink-0" />
            : <ChevronRight size={11} className="text-gray-400 shrink-0 opacity-0 group-hover:opacity-100" />
          }
        </button>
        <DropdownMenu open={projectMenuOpen} onOpenChange={setProjectMenuOpen}>
          <DropdownMenuTrigger asChild>
            <button
              className={cn(
                "p-0.5 rounded text-gray-400 hover:text-gray-600 transition-colors shrink-0",
                projectMenuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100"
              )}
              onClick={e => e.stopPropagation()}
            >
              <MoreHorizontal size={12} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44 text-xs">
            <DropdownMenuItem onClick={onStartRenameProject} className="gap-2 text-xs">
              <Pencil size={12} />
              Переименовать
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={onDeleteProject}
              className="gap-2 text-xs text-red-600 focus:text-red-600 focus:bg-red-50"
            >
              <Trash2 size={12} />
              Удалить проект
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      )}

      {expanded && (
        <div className="ml-3 pl-2 border-l border-[#E8E6E1] dark:border-[#2a2d3a] mt-0.5 space-y-0.5">
          {chats.map(chat => (
            <ChatRow
              key={chat.id}
              chat={chat}
              active={activeChat === chat.id}
              renaming={renamingChat === chat.id}
              renameValue={renameValue}
              renameInputRef={renameInputRef}
              onRenameChange={onRenameChange}
              onRenameSubmit={onRenameSubmit}
              onClick={() => onChatSelect(chat.id)}
              onRename={() => onRenameChat(chat)}
              onDelete={() => onDeleteChat(chat.id)}
              onMove={(pid) => onMoveChat(chat.id, pid)}
              projects={allProjects}
              isPinned={pinnedChats?.has(chat.id)}
              onPin={onPinChat ? () => onPinChat(chat.id) : undefined}
            />
          ))}
          {/* New chat button */}
          <button
            onClick={onCreateChat}
            className="w-full flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-white dark:hover:bg-[#1e2130] transition-colors"
          >
            <Plus size={11} />
            Новая задача
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Chat Row ─────────────────────────────────────────────────────────────────

function ChatRow({
  chat, active, renaming, renameValue, renameInputRef,
  onRenameChange, onRenameSubmit,
  onClick, onRename, onDelete, onMove, projects, isPinned, onPin
}: {
  chat: Chat;
  active: boolean;
  renaming: boolean;
  renameValue: string;
  renameInputRef: React.RefObject<HTMLInputElement | null>;
  onRenameChange: (v: string) => void;
  onRenameSubmit: () => void;
  onClick: () => void;
  onRename: () => void;
  onDelete: () => void;
  onMove: (projectId: string) => void;
  projects: Project[];
  isPinned?: boolean;
  onPin?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  if (renaming) {
    return (
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-white border border-indigo-300">
        <input
          ref={renameInputRef}
          type="text"
          value={renameValue}
          onChange={e => onRenameChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter") onRenameSubmit();
            if (e.key === "Escape") onRenameSubmit();
          }}
          onBlur={onRenameSubmit}
          className="flex-1 text-xs bg-transparent focus:outline-none text-gray-800"
        />
      </div>
    );
  }

  const STATUS_DOT: Record<string, string> = {
    executing:    "bg-indigo-500 animate-pulse",
    thinking:     "bg-amber-400 animate-pulse",
    completed:    "bg-green-500",
    failed:       "bg-red-500",
    idle:         "bg-gray-300",
    searching:    "bg-blue-400 animate-pulse",
    verifying:    "bg-purple-400 animate-pulse",
    waiting:      "bg-yellow-400",
    partial:      "bg-orange-400",
    needs_review: "bg-yellow-400",
  };

  const isNeedsReview = chat.status === "needs_review";

  return (
    <div className={cn(
      "group flex items-start gap-1.5 px-2 py-1.5 rounded-md transition-colors cursor-pointer",
      active ? "bg-white dark:bg-[#1e2130] shadow-sm" : "hover:bg-white/70 dark:hover:bg-[#1e2130]/70",
      isNeedsReview && !active && "hover:bg-yellow-50/60 dark:hover:bg-yellow-900/20"
    )}>
      {isNeedsReview ? (
        <AlertTriangle size={11} className="text-yellow-500 mt-1 shrink-0" />
      ) : (
        <span className={cn("w-1.5 h-1.5 rounded-full mt-1.5 shrink-0", STATUS_DOT[chat.status] ?? "bg-gray-300")} />
      )}
      <div className="flex-1 min-w-0" onClick={onClick}>
        <span className={cn(
          "block text-xs truncate leading-tight",
          isNeedsReview ? "text-yellow-800 dark:text-yellow-400 font-medium" : "text-gray-700 dark:text-gray-300"
        )}>{chat.title}</span>
        <div className="flex items-center gap-1.5 mt-0.5">
          {chat.cost > 0 && (
            <span className="text-[10px] text-gray-400 font-mono">${chat.cost.toFixed(2)}</span>
          )}
          {chat.duration && chat.duration !== "0s" && (
            <span className="text-[10px] text-gray-400">{chat.duration}</span>
          )}
        </div>
      </div>

      {/* Context menu */}
      <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
        <DropdownMenuTrigger asChild>
          <button
            className={cn(
              "p-0.5 rounded text-gray-400 hover:text-gray-600 transition-colors",
              menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100"
            )}
            onClick={e => e.stopPropagation()}
          >
            <MoreHorizontal size={12} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44 text-xs">
          <DropdownMenuItem onClick={onRename} className="gap-2 text-xs">
            <Pencil size={12} />
            Переименовать
          </DropdownMenuItem>
          {onPin && (
            <DropdownMenuItem onClick={onPin} className="gap-2 text-xs">
              {isPinned ? <PinOff size={12} /> : <Pin size={12} />}
              {isPinned ? "Открепить" : "Закрепить"}
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          {projects.map(p => p.id !== chat.projectId && (
            <DropdownMenuItem key={p.id} onClick={() => onMove(p.id)} className="gap-2 text-xs">
              <FolderInput size={12} />
              Переместить в {p.name}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={onDelete}
            className="gap-2 text-xs text-red-600 focus:text-red-600 focus:bg-red-50"
          >
            <Trash2 size={12} />
            Удалить
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

// ─── User Avatar Row ─────────────────────────────────────────────────────────

function UserAvatarRow({
  onSettingsClick,
  notifications = [],
  onMarkRead,
  onMarkAllRead,
  onDismissNotif,
  onClearAllNotifs,
}: {
  onSettingsClick?: () => void;
  notifications?: AppNotification[];
  onMarkRead?: (id: string) => void;
  onMarkAllRead?: () => void;
  onDismissNotif?: (id: string) => void;
  onClearAllNotifs?: () => void;
}) {
  const { currentUser } = useCurrentUser();
  const roleColors = ROLE_COLORS[currentUser.role];
  const initials = currentUser.name.split(" ").map(w => w[0]).slice(0, 2).join("");

  return (
    <div
      className="flex items-center gap-2 px-2 py-1.5 mt-0.5 rounded-md hover:bg-white dark:hover:bg-[#1e2130] transition-colors cursor-pointer"
      onClick={() => onSettingsClick?.()}
      title="Настройки пользователя"
    >
      <div className={cn(
        "w-5 h-5 rounded-full flex items-center justify-center shrink-0",
        roleColors.bg
      )}>
        <span className={cn("text-[9px] font-semibold", roleColors.text)}>{initials}</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-gray-700 dark:text-gray-200 truncate">{currentUser.name}</div>
      </div>
      {/* Bell notification center */}
      <div onClick={e => e.stopPropagation()}>
        <NotificationCenter
          notifications={notifications}
          onMarkRead={onMarkRead ?? (() => {})}
          onMarkAllRead={onMarkAllRead ?? (() => {})}
          onDismiss={onDismissNotif ?? (() => {})}
          onClearAll={onClearAllNotifs ?? (() => {})}
        />
      </div>
    </div>
  );
}
