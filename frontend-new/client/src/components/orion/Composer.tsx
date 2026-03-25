// ORION Composer — clean input area with drag & drop + capability badges
// Model selector is in the header. Layout: [attach] [textarea] [mic] [send]
// Bottom row: capability badges (Search / Browser / SSH / Files / Images)

import { useState, useRef, useCallback, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Paperclip, ArrowUp, Mic, X, Search, Globe, Terminal, FolderOpen, Image, AtSign, Server, Database, Code2, FileText, AlertTriangle, ShieldOff, Square } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";

const MENTION_ITEMS = [
  { id: "server1", label: "185.22.xx.xx", desc: "Production server", icon: <Server size={11} className="text-blue-500" /> },
  { id: "server2", label: "dev.example.com", desc: "Dev server", icon: <Server size={11} className="text-green-500" /> },
  { id: "db1", label: "mysql:bitrix_db", desc: "MySQL database", icon: <Database size={11} className="text-amber-500" /> },
  { id: "repo1", label: "github:myorg/myapp", desc: "GitHub repo", icon: <Code2 size={11} className="text-purple-500" /> },
  { id: "file1", label: "nginx.conf", desc: "Nginx config file", icon: <FileText size={11} className="text-gray-500" /> },
  { id: "file2", label: "docker-compose.yml", desc: "Docker compose", icon: <FileText size={11} className="text-blue-400" /> },
];

interface UploadFile {
  name: string;
  progress: number;
  id: string;
}

const CAPABILITIES = [
  { id: "search", label: "Поиск", icon: <Search size={10} />, color: "text-blue-600 bg-blue-50 border-blue-200 hover:bg-blue-100" },
  { id: "browser", label: "Браузер", icon: <Globe size={10} />, color: "text-violet-600 bg-violet-50 border-violet-200 hover:bg-violet-100" },
  { id: "ssh", label: "SSH", icon: <Terminal size={10} />, color: "text-green-600 bg-green-50 border-green-200 hover:bg-green-100" },
  { id: "files", label: "Файлы", icon: <FolderOpen size={10} />, color: "text-amber-600 bg-amber-50 border-amber-200 hover:bg-amber-100" },
  { id: "images", label: "Изображения", icon: <Image size={10} />, color: "text-rose-600 bg-rose-50 border-rose-200 hover:bg-rose-100" },
] as const;

interface ComposerProps {
  onSend: (text: string) => void;
  budgetExhausted?: boolean;
  onAdminRefill?: () => void;
  isRunning?: boolean;
  onStop?: () => void;
}

const DRAFT_KEY = "orion_composer_draft";

function getDraft(): string {
  try { return localStorage.getItem(DRAFT_KEY) || ""; } catch { return ""; }
}
function saveDraft(v: string) {
  try { localStorage.setItem(DRAFT_KEY, v); } catch { /* ignore */ }
}
function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
}

export function Composer({ onSend, budgetExhausted = false, onAdminRefill, isRunning = false, onStop }: ComposerProps) {
  const [value, setValue] = useState(getDraft);
  const [uploadFiles, setUploadFiles] = useState<UploadFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [activeCaps, setActiveCaps] = useState<Set<string>>(new Set(["search", "browser", "ssh"]));
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value;
    setValue(v);
    saveDraft(v);
    adjustHeight();
    // Detect @mention trigger
    const cursor = e.target.selectionStart ?? v.length;
    const textBefore = v.slice(0, cursor);
    const match = textBefore.match(/@([\w.-]*)$/);
    if (match) {
      setMentionQuery(match[1]);
      setMentionOpen(true);
      setMentionIndex(0);
    } else {
      setMentionOpen(false);
    }
  };

  const handleSend = () => {
    const text = value.trim();
    if (!text) return;
    onSend(text);
    setValue("");
    clearDraft();
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const insertMention = (item: typeof MENTION_ITEMS[0]) => {
    const cursor = textareaRef.current?.selectionStart ?? value.length;
    const textBefore = value.slice(0, cursor);
    const textAfter = value.slice(cursor);
    const replaced = textBefore.replace(/@[\w.-]*$/, `@${item.label} `);
    setValue(replaced + textAfter);
    setMentionOpen(false);
    setTimeout(() => {
      textareaRef.current?.focus();
      adjustHeight();
    }, 10);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mentionOpen && mentionItems.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setMentionIndex(i => Math.min(i + 1, mentionItems.length - 1)); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setMentionIndex(i => Math.max(i - 1, 0)); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); insertMention(mentionItems[mentionIndex]); return; }
      if (e.key === "Escape") { setMentionOpen(false); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const simulateUpload = (file: File) => {
    const id = `${file.name}-${Date.now()}`;
    setUploadFiles(prev => [...prev, { name: file.name, progress: 0, id }]);
    let p = 0;
    const interval = setInterval(() => {
      p += Math.random() * 20 + 8;
      if (p >= 100) {
        p = 100;
        clearInterval(interval);
        setTimeout(() => {
          setUploadFiles(prev => prev.filter(f => f.id !== id));
          toast.success(`${file.name} загружен`);
        }, 600);
      }
      setUploadFiles(prev =>
        prev.map(f => f.id === id ? { ...f, progress: Math.min(p, 100) } : f)
      );
    }, 180);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    Array.from(e.target.files ?? []).forEach(simulateUpload);
    e.target.value = "";
  };

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsDragging(false);
  };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    files.forEach(file => {
      // For text files, read content and insert into textarea
      const isText = file.type.startsWith('text/') || /\.(txt|md|json|yaml|yml|xml|csv|log|sh|py|js|ts|jsx|tsx|html|css|conf|env|ini|toml)$/i.test(file.name);
      if (isText && file.size < 50000) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          const content = ev.target?.result as string;
          const snippet = `\n\`\`\`${file.name}\n${content.slice(0, 3000)}${content.length > 3000 ? '\n... (обрезано)' : ''}\n\`\`\``;
          setValue(prev => prev + snippet);
          setTimeout(adjustHeight, 10);
        };
        reader.readAsText(file);
      } else {
        simulateUpload(file);
      }
    });
  };

  const handleVoice = () => {
    if (isRecording) {
      setIsRecording(false);
      toast.info("Голосовой ввод остановлен");
    } else {
      setIsRecording(true);
      toast.info("Запись голоса... (демо)");
      setTimeout(() => {
        setIsRecording(false);
        setValue(prev => prev + (prev ? " " : "") + "Установи Bitrix на сервер 185.22.xx.xx");
        adjustHeight();
        setTimeout(adjustHeight, 50);
      }, 2500);
    }
  };

  const toggleCap = (id: string) => {
    setActiveCaps(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // @mention state
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionIndex, setMentionIndex] = useState(0);

  const mentionItems = mentionQuery
    ? MENTION_ITEMS.filter(m => m.label.toLowerCase().includes(mentionQuery.toLowerCase()) || m.desc.toLowerCase().includes(mentionQuery.toLowerCase()))
    : MENTION_ITEMS;

  const canSend = value.trim().length > 0 && !isRecording && !budgetExhausted;

  return (
    <div
      className={cn(
        "border-t border-[#E8E6E1] dark:border-[#2a2d3a] bg-white dark:bg-[#0f1117] px-4 pt-3 pb-3 transition-colors relative",
        isDragging && "bg-indigo-50 dark:bg-indigo-900/20 border-indigo-300"
      )}
      onDragOver={!budgetExhausted ? handleDragOver : undefined}
      onDragLeave={!budgetExhausted ? handleDragLeave : undefined}
      onDrop={!budgetExhausted ? handleDrop : undefined}
    >
      {/* Budget exhausted lock banner */}
      {budgetExhausted && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-white/95 dark:bg-[#0f1117]/95 backdrop-blur-sm rounded-b-none">
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
            <ShieldOff size={15} className="text-red-500 shrink-0" />
            <div>
              <div className="text-xs font-semibold text-red-700 dark:text-red-400">Бюджет исчерпан</div>
              <div className="text-[10px] text-red-500 dark:text-red-500">Новые задачи заблокированы. Обратитесь к администратору.</div>
            </div>
            {onAdminRefill && (
              <button
                onClick={onAdminRefill}
                className="ml-2 shrink-0 px-2.5 py-1 rounded-lg bg-red-600 hover:bg-red-700 text-white text-[10px] font-semibold transition-colors"
              >
                Пополнить
              </button>
            )}
          </div>
        </div>
      )}
      {/* Drag overlay */}
      <AnimatePresence>
        {isDragging && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 z-10 flex items-center justify-center border-2 border-dashed border-indigo-400 bg-indigo-50/80 pointer-events-none"
          >
            <div className="flex flex-col items-center gap-1.5">
              <Paperclip size={20} className="text-indigo-500" />
              <span className="text-sm font-medium text-indigo-600">Перетащите файлы сюда</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Upload progress pills */}
      <AnimatePresence>
        {uploadFiles.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex flex-wrap gap-2 mb-2 overflow-hidden"
          >
            {uploadFiles.map(f => (
              <motion.div
                key={f.id}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-gray-50 border border-gray-200 text-xs text-gray-600 max-w-[200px]"
              >
                <div className="flex-1 min-w-0">
                  <div className="truncate font-medium">{f.name}</div>
                  <div className="mt-1 h-1 rounded-full bg-gray-200 overflow-hidden">
                    <motion.div
                      className="h-full rounded-full bg-indigo-500"
                      initial={{ width: 0 }}
                      animate={{ width: `${f.progress}%` }}
                      transition={{ duration: 0.15 }}
                    />
                  </div>
                </div>
                <span className="shrink-0 font-mono text-[10px] text-gray-400">{Math.round(f.progress)}%</span>
                <button onClick={() => setUploadFiles(prev => prev.filter(u => u.id !== f.id))} className="shrink-0 text-gray-300 hover:text-gray-500 transition-colors">
                  <X size={10} />
                </button>
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Voice recording indicator */}
      <AnimatePresence>
        {isRecording && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            className="flex items-center gap-2 mb-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200"
          >
            <div className="flex items-center gap-1">
              {[0, 1, 2, 3].map(i => (
                <motion.div
                  key={i}
                  className="w-0.5 bg-red-500 rounded-full"
                  animate={{ height: [4, 12, 6, 14, 4] }}
                  transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.1 }}
                />
              ))}
            </div>
            <span className="text-xs text-red-600 font-medium">Запись голоса...</span>
            <button onClick={handleVoice} className="ml-auto text-red-400 hover:text-red-600 transition-colors">
              <X size={12} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* @mention dropdown */}
      <AnimatePresence>
        {mentionOpen && mentionItems.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.12 }}
            className="absolute bottom-full left-4 right-4 mb-2 bg-white dark:bg-[#1a1d2e] border border-[#E8E6E1] dark:border-[#2a2d3a] rounded-xl shadow-lg overflow-hidden z-50"
          >
            <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-[#E8E6E1] dark:border-[#2a2d3a] bg-gray-50 dark:bg-[#1e2130]">
              <AtSign size={10} className="text-indigo-500" />
              <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Упомянуть</span>
            </div>
            {mentionItems.slice(0, 6).map((item, idx) => (
              <button
                key={item.id}
                onClick={() => insertMention(item)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors",
                  idx === mentionIndex ? "bg-indigo-50 dark:bg-indigo-900/30" : "hover:bg-gray-50 dark:hover:bg-[#1e2130]"
                )}
              >
                <div className="w-5 h-5 rounded bg-gray-100 flex items-center justify-center shrink-0">{item.icon}</div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate">@{item.label}</div>
                  <div className="text-[10px] text-gray-400 dark:text-gray-500 truncate">{item.desc}</div>
                </div>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main input row */}
      <div className="flex items-end gap-2">
        {/* Attach */}
        <button
          onClick={() => fileInputRef.current?.click()}
          className="shrink-0 p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors mb-0.5"
          title="Прикрепить файл"
        >
          <Paperclip size={16} />
        </button>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileChange} />

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={isRunning ? "Отправьте дополнение к задаче..." : "Поставьте задачу агенту..."}
          rows={1}
          className={cn(
            "flex-1 resize-none bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 dark:placeholder:text-gray-500",
            "outline-none border-none focus:ring-0 leading-relaxed py-2",
            "min-h-[36px] max-h-[200px]"
          )}
          style={{ height: "36px" }}
        />

        {/* Voice */}
        <button
          onClick={handleVoice}
          className={cn(
            "shrink-0 p-2 rounded-lg transition-all mb-0.5",
            isRecording ? "bg-red-100 text-red-500 animate-pulse" : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"
          )}
          title="Голосовой ввод"
        >
          <Mic size={15} />
        </button>

        {/* Stop button — shown when agent is running */}
        {isRunning && onStop && (
          <button
            onClick={onStop}
            className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-red-500 hover:bg-red-600 text-white transition-all mb-0.5 shadow-sm"
            title="Остановить"
          >
            <Square size={12} fill="currentColor" />
          </button>
        )}
        {/* Send */}
        <button
          onClick={handleSend}
          disabled={!canSend}
          className={cn(
            "shrink-0 w-8 h-8 rounded-full flex items-center justify-center transition-all mb-0.5",
            canSend ? "bg-gray-900 dark:bg-indigo-600 text-white hover:bg-gray-700 dark:hover:bg-indigo-500 shadow-sm" : "bg-gray-100 dark:bg-[#1e2130] text-gray-300 dark:text-gray-600 cursor-not-allowed"
          )}
        >
          <ArrowUp size={15} />
        </button>
      </div>

      {/* Bottom row: capability badges + hint */}
      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        {CAPABILITIES.map(cap => (
          <button
            key={cap.id}
            onClick={() => toggleCap(cap.id)}
            title={activeCaps.has(cap.id) ? `${cap.label} включён` : `${cap.label} выключен`}
            className={cn(
              "flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border transition-all",
              activeCaps.has(cap.id)
                ? cap.color
                : "text-gray-300 bg-transparent border-gray-200 hover:border-gray-300 hover:text-gray-400"
            )}
          >
            {cap.icon}
            {cap.label}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-gray-300">Enter — отправить · Shift+Enter — новая строка</span>
      </div>
    </div>
  );
}
