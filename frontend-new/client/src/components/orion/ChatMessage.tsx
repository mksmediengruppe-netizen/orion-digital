// Design: "Warm Intelligence"
// Features: rich markdown, artifacts (HTML preview), follow-ups, star rating
// NEW: inline edit for user messages, reactions (👍/👎) on agent messages, copy as markdown, collapsible steps

import { cn } from "@/lib/utils";
import type { Message, Step, ViewerArtifact } from "@/lib/mockData";
import { StepChip } from "./StepChip";
import { MarkdownContent } from "./MarkdownContent";
import {
  Bot, User, FileText, FileCode, Image as ImageIcon, Download,
  Globe, ExternalLink, Star, ArrowRight, X, Maximize2, Minimize2,
  ThumbsUp, ThumbsDown, Copy, Check, Pencil, ChevronDown, ChevronRight,
  Code2, FileJson, Layers, Eye
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useRef, useEffect } from "react";
import { toast } from "sonner";

interface ChatMessageProps {
  message: Message;
  activeStep?: string;
  onStepClick: (step: Step) => void;
  isLast?: boolean;
  isCompleted?: boolean;
  onEdit?: (messageId: string, newContent: string) => void;
  onArtifactOpen?: (artifact: ViewerArtifact) => void;
}

const ARTIFACT_ICONS: Record<string, React.ReactNode> = {
  document: <FileText size={14} className="text-blue-500" />,
  code:     <FileCode size={14} className="text-emerald-500" />,
  image:    <ImageIcon size={14} className="text-purple-500" />,
  report:   <FileText size={14} className="text-amber-500" />,
  html:     <Globe size={14} className="text-orange-500" />,
  site:     <Globe size={14} className="text-indigo-500" />,
  markdown: <FileText size={14} className="text-teal-500" />,
  diff:     <Code2 size={14} className="text-rose-500" />,
};

// ─── Viewer Artifact Cards (new rich artifacts with ArtifactViewer) ─────────────

const VIEWER_ARTIFACT_TYPE_ICONS: Record<string, React.ReactNode> = {
  html:     <Globe size={13} className="text-orange-500" />,
  code:     <FileCode size={13} className="text-emerald-500" />,
  markdown: <FileText size={13} className="text-teal-500" />,
  image:    <ImageIcon size={13} className="text-purple-500" />,
  diff:     <Code2 size={13} className="text-rose-500" />,
};

const VIEWER_ARTIFACT_TYPE_LABELS: Record<string, string> = {
  html: "HTML Preview",
  code: "Code",
  markdown: "Markdown",
  image: "Image",
  diff: "Diff",
};

function ViewerArtifactCards({
  artifacts,
  onOpen,
}: {
  artifacts: ViewerArtifact[];
  onOpen: (a: ViewerArtifact) => void;
}) {
  return (
    <div className="mt-2 flex flex-col gap-1.5">
      {artifacts.map((artifact, i) => (
        <motion.div
          key={artifact.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, delay: i * 0.07 }}
        >
          <button
            onClick={() => onOpen(artifact)}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-[#E8E6E1] dark:border-[#2a2d3a] bg-[#F8F7F5] dark:bg-[#1a1d2e] hover:bg-white dark:hover:bg-[#1e2130] hover:border-indigo-200 dark:hover:border-indigo-700 transition-all cursor-pointer group text-left"
          >
            <div className="w-7 h-7 rounded-lg bg-white dark:bg-[#252840] border border-[#E8E6E1] dark:border-[#2a2d3a] flex items-center justify-center shrink-0">
              {VIEWER_ARTIFACT_TYPE_ICONS[artifact.type] ?? <FileText size={13} className="text-gray-400" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate">{artifact.title}</div>
              <div className="text-[10px] text-gray-400 flex items-center gap-1.5">
                <span>{VIEWER_ARTIFACT_TYPE_LABELS[artifact.type] ?? artifact.type}</span>
                {artifact.size && <><span>·</span><span>{artifact.size}</span></>}
                {artifact.originalContent && (
                  <span className="text-rose-400 font-medium">· diff</span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <span className="text-[10px] text-indigo-500 font-medium flex items-center gap-0.5">
                <Eye size={10} />
                Открыть
              </span>
            </div>
          </button>
        </motion.div>
      ))}
    </div>
  );
}

const HTML_PREVIEW_DOC = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:-apple-system,sans-serif;margin:0;padding:16px;background:#fff;font-size:13px}h1{color:#e31e24;font-size:18px;margin:0 0 4px}.badge{display:inline-block;background:#e8f4fd;color:#1565c0;border-radius:4px;padding:2px 8px;font-size:11px;margin-bottom:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}.card{border:1px solid #e0e0e0;border-radius:8px;padding:12px}.card-title{font-weight:600;color:#333;margin-bottom:4px;font-size:12px}.card-val{font-size:18px;font-weight:700;color:#1a1a1a}.ok{color:#2e7d32;font-size:11px}.url{background:#f5f5f5;border-radius:4px;padding:8px 10px;font-family:monospace;font-size:11px;color:#333;margin-bottom:8px}.status{display:flex;align-items:center;gap:6px;font-size:12px;color:#2e7d32}.dot{width:8px;height:8px;border-radius:50%;background:#4caf50}</style></head><body><h1>1С-Битрикс: Управление сайтом</h1><span class="badge">Версия 23.850 · Установлен</span><div class="grid"><div class="card"><div class="card-title">PHP</div><div class="card-val">8.2.10</div><div class="ok">✓ Все модули активны</div></div><div class="card"><div class="card-title">MySQL</div><div class="card-val">8.0.35</div><div class="ok">✓ База данных создана</div></div></div><div class="url">http://185.22.xx.xx/bitrix/admin/</div><div class="status"><div class="dot"></div>Сайт работает · Административная панель доступна</div></body></html>`;

function ArtifactCard({ artifact }: { artifact: NonNullable<Message["artifact"]> }) {
  const [showPreview, setShowPreview] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const canPreview = artifact.type === "html" || artifact.type === "site" || (artifact.name?.endsWith(".html") ?? false);

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: 0.1 }} className="mt-2">
      <div
        className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-[#E8E6E1] bg-[#F8F7F5] hover:bg-white transition-colors cursor-pointer group"
        onClick={() => canPreview ? setShowPreview(v => !v) : toast.info("Скачивание файла...")}
      >
        <div className="w-7 h-7 rounded-lg bg-white border border-[#E8E6E1] flex items-center justify-center shrink-0">
          {ARTIFACT_ICONS[artifact.type] ?? <FileText size={14} className="text-gray-400" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-gray-800 truncate">{artifact.name}</div>
          <div className="text-[10px] text-gray-400">{artifact.size} · {artifact.createdAt}</div>
        </div>
        <div className="flex items-center gap-1">
          {canPreview && (
            <button
              className="p-1 rounded hover:bg-indigo-100 text-indigo-400 hover:text-indigo-600 transition-colors opacity-0 group-hover:opacity-100"
              onClick={e => { e.stopPropagation(); setShowPreview(v => !v); }}
              title="Предпросмотр"
            >
              <ExternalLink size={12} />
            </button>
          )}
          <button
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors opacity-0 group-hover:opacity-100"
            onClick={e => { e.stopPropagation(); toast.info("Скачивание..."); }}
            title="Скачать"
          >
            <Download size={12} />
          </button>
        </div>
      </div>
      <AnimatePresence>
        {showPreview && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: expanded ? 400 : 220, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="mt-1.5 rounded-xl border border-[#E8E6E1] overflow-hidden"
          >
            <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 border-b border-gray-100">
              <Globe size={11} className="text-gray-400" />
              <span className="text-[11px] text-gray-500 flex-1 font-mono truncate">{artifact.name}</span>
              <button onClick={() => setExpanded(v => !v)} className="p-0.5 rounded hover:bg-gray-200 text-gray-400 transition-colors">
                {expanded ? <Minimize2 size={11} /> : <Maximize2 size={11} />}
              </button>
              <button onClick={() => setShowPreview(false)} className="p-0.5 rounded hover:bg-gray-200 text-gray-400 transition-colors">
                <X size={11} />
              </button>
            </div>
            <iframe
              srcDoc={HTML_PREVIEW_DOC}
              className="w-full border-0"
              style={{ height: expanded ? 360 : 180 }}
              sandbox="allow-same-origin"
              title="Предпросмотр"
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function StarRating() {
  const [rating, setRating] = useState(0);
  const [hovered, setHovered] = useState(0);
  const [submitted, setSubmitted] = useState(false);

  if (submitted) {
    return (
      <div className="text-[11px] text-gray-400 flex items-center gap-1">
        <Star size={11} className="text-amber-400" fill="currentColor" />
        Спасибо за оценку!
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-gray-400">Как вам результат?</span>
      <div className="flex items-center gap-0.5">
        {[1, 2, 3, 4, 5].map(i => (
          <button
            key={i}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(0)}
            onClick={() => { setRating(i); setSubmitted(true); toast.success("Оценка сохранена"); }}
            className="transition-transform hover:scale-110"
          >
            <Star
              size={14}
              className={cn("transition-colors", (hovered || rating) >= i ? "text-amber-400" : "text-gray-200")}
              fill={(hovered || rating) >= i ? "currentColor" : "none"}
            />
          </button>
        ))}
      </div>
    </div>
  );
}

const FOLLOW_UPS = [
  "Настроить SSL сертификат через Let's Encrypt",
  "Создать резервную копию базы данных",
  "Настроить автообновление Bitrix",
  "Оптимизировать производительность сервера",
];

function SuggestedFollowUps() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.2 }}
      className="mt-3 space-y-1.5"
    >
      <div className="text-[11px] text-gray-400 font-medium uppercase tracking-wider px-0.5">
        Suggested follow-ups
      </div>
      {FOLLOW_UPS.map((text, i) => (
        <motion.button
          key={i}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.2, delay: 0.1 + i * 0.05 }}
          onClick={() => toast.info(`Задача: ${text}`)}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-[#E8E6E1] bg-white hover:border-indigo-200 hover:bg-indigo-50/40 text-left text-xs text-gray-600 hover:text-gray-800 transition-all group"
        >
          <span className="flex-1">{text}</span>
          <ArrowRight size={11} className="text-gray-300 group-hover:text-indigo-400 transition-colors shrink-0" />
        </motion.button>
      ))}
    </motion.div>
  );
}

// ─── Agent Message Reactions ─────────────────────────────────────────────────

function MessageReactions({ content }: { content: string }) {
  const [reaction, setReaction] = useState<"up" | "down" | null>(null);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success("Скопировано в буфер");
  };

  const handleReact = (r: "up" | "down") => {
    if (reaction === r) {
      setReaction(null);
    } else {
      setReaction(r);
      toast.success(r === "up" ? "Положительный отзыв отправлен" : "Отрицательный отзыв отправлен");
    }
  };

  return (
    <div className="flex items-center gap-1 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        onClick={() => handleReact("up")}
        title="Полезно"
        className={cn(
          "p-1 rounded transition-colors",
          reaction === "up"
            ? "text-green-600 bg-green-50"
            : "text-gray-300 hover:text-gray-500 hover:bg-gray-100"
        )}
      >
        <ThumbsUp size={11} />
      </button>
      <button
        onClick={() => handleReact("down")}
        title="Не полезно"
        className={cn(
          "p-1 rounded transition-colors",
          reaction === "down"
            ? "text-red-500 bg-red-50"
            : "text-gray-300 hover:text-gray-500 hover:bg-gray-100"
        )}
      >
        <ThumbsDown size={11} />
      </button>
      <button
        onClick={handleCopy}
        title="Копировать как Markdown"
        className="p-1 rounded text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-colors"
      >
        {copied ? <Check size={11} className="text-green-500" /> : <Copy size={11} />}
      </button>
    </div>
  );
}

// ─── Collapsible Steps ────────────────────────────────────────────────────────

function CollapsibleSteps({
  steps, activeStep, onStepClick
}: {
  steps: Step[];
  activeStep?: string;
  onStepClick: (step: Step) => void;
}) {
  const [collapsed, setCollapsed] = useState(steps.length > 4);

  const visibleSteps = collapsed ? steps.slice(0, 3) : steps;
  const hiddenCount = steps.length - 3;

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-1.5">
        <AnimatePresence initial={false}>
          {visibleSteps.map((step, i) => (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, scale: 0.8, y: 6 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.8 }}
              transition={{ duration: 0.22, ease: "easeOut", delay: i * 0.03 }}
            >
              <StepChip step={step} active={activeStep === step.id} onClick={onStepClick} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      {steps.length > 4 && (
        <button
          onClick={() => setCollapsed(v => !v)}
          className="mt-1.5 flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600 transition-colors"
        >
          {collapsed ? (
            <>
              <ChevronRight size={11} />
              Ещё {hiddenCount} шагов
            </>
          ) : (
            <>
              <ChevronDown size={11} />
              Свернуть
            </>
          )}
        </button>
      )}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function ChatMessage({ message, activeStep, onStepClick, isLast, isCompleted, onEdit, onArtifactOpen }: ChatMessageProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(message.content);
  const editRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (isEditing && editRef.current) {
      editRef.current.focus();
      editRef.current.style.height = "auto";
      editRef.current.style.height = editRef.current.scrollHeight + "px";
    }
  }, [isEditing]);

  const handleEditSubmit = () => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== message.content) {
      onEdit?.(message.id, trimmed);
      toast.success("Сообщение изменено — задача перезапущена");
    }
    setIsEditing(false);
  };

  if (message.role === "system") {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.92 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="flex flex-col items-center py-2 gap-2"
      >
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-[#1e2130] text-xs text-gray-500 dark:text-gray-400">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 live-pulse" />
          {message.content}
        </div>
        {message.viewerArtifacts && message.viewerArtifacts.length > 0 && onArtifactOpen && (
          <div className="w-full max-w-sm px-4">
            <ViewerArtifactCards artifacts={message.viewerArtifacts} onOpen={onArtifactOpen} />
          </div>
        )}
      </motion.div>
    );
  }

  if (message.role === "user") {
    return (
      <motion.div
        initial={{ opacity: 0, x: 24, y: 8 }}
        animate={{ opacity: 1, x: 0, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="flex gap-3 justify-end group"
      >
        <div className="max-w-[80%]">
          {isEditing ? (
            <div className="bg-indigo-50 border border-indigo-200 rounded-2xl rounded-tr-sm px-4 py-3">
              <textarea
                ref={editRef}
                value={editValue}
                onChange={e => {
                  setEditValue(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = e.target.scrollHeight + "px";
                }}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleEditSubmit(); }
                  if (e.key === "Escape") { setIsEditing(false); setEditValue(message.content); }
                }}
                className="w-full text-sm text-gray-800 bg-transparent resize-none outline-none leading-relaxed min-w-[200px]"
                rows={1}
              />
              <div className="flex items-center gap-2 mt-2 pt-2 border-t border-indigo-200">
                <button
                  onClick={handleEditSubmit}
                  className="px-3 py-1 rounded-lg bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 transition-colors"
                >
                  Сохранить и перезапустить
                </button>
                <button
                  onClick={() => { setIsEditing(false); setEditValue(message.content); }}
                  className="px-3 py-1 rounded-lg text-xs text-gray-500 hover:bg-gray-100 transition-colors"
                >
                  Отмена
                </button>
                <span className="ml-auto text-[10px] text-gray-400">Enter — сохранить · Esc — отмена</span>
              </div>
            </div>
          ) : (
            <div className="relative">
              <div className="bg-indigo-600 dark:bg-indigo-700 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap">
                {message.content}
              </div>
              {/* Edit button — appears on hover */}
              <button
                onClick={() => setIsEditing(true)}
                title="Редактировать сообщение"
                className="absolute -left-7 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-gray-300 hover:text-gray-500 hover:bg-gray-100 transition-all opacity-0 group-hover:opacity-100"
              >
                <Pencil size={11} />
              </button>
            </div>
          )}
          <div className="text-[10px] text-gray-400 mt-1 text-right">{message.timestamp}</div>
        </div>
        <div className="w-7 h-7 rounded-full bg-indigo-100 dark:bg-indigo-900/40 flex items-center justify-center shrink-0 mt-1">
          <User size={13} className="text-indigo-600" />
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: -16, y: 8 }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="flex gap-3 group"
    >
      <div className="w-7 h-7 rounded-full bg-gray-100 dark:bg-[#1e2130] border border-gray-200 dark:border-[#2a2d3a] flex items-center justify-center shrink-0 mt-1">
        <Bot size={13} className="text-gray-600 dark:text-gray-400" />
      </div>
      <div className="flex-1 min-w-0">
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: 0.08 }}
          className="bg-white dark:bg-[#1a1d2e] border border-[#E8E6E1] dark:border-[#2a2d3a] rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm"
        >
          <MarkdownContent content={message.content} />
        </motion.div>

        {/* Collapsible steps */}
        {message.steps && message.steps.length > 0 && (
          <CollapsibleSteps
            steps={message.steps}
            activeStep={activeStep}
            onStepClick={onStepClick}
          />
        )}

        {message.artifact && <ArtifactCard artifact={message.artifact} />}

        {/* Viewer Artifact Cards */}
        {message.viewerArtifacts && message.viewerArtifacts.length > 0 && onArtifactOpen && (
          <ViewerArtifactCards artifacts={message.viewerArtifacts} onOpen={onArtifactOpen} />
        )}

        {/* Reactions + copy */}
        <MessageReactions content={message.content} />

        {isLast && isCompleted && (
          <div className="mt-3 space-y-2">
            <StarRating />
            <SuggestedFollowUps />
          </div>
        )}

        <div className="text-[10px] text-gray-400 mt-1.5">{message.timestamp}</div>
      </div>
    </motion.div>
  );
}
