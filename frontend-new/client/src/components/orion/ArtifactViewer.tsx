// ORION ArtifactViewer — "Warm Intelligence" design
// Preview and edit artifacts created by the agent: HTML pages, code, markdown docs
// Inspired by Claude Artifacts + Manus document editor

import { useState, useRef, useCallback } from "react";
import { cn } from "@/lib/utils";
import {
  Eye, Code2, FileText, Download, Copy, Check, RefreshCw,
  Maximize2, Minimize2, X, Pencil, Save, RotateCcw, ChevronRight,
  ChevronDown, Play, ExternalLink, Split, Globe, FileCode,
  Image as ImageIcon, File, Diff
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";

// ─── Artifact types ───────────────────────────────────────────────────────────

export type ArtifactType = "html" | "code" | "markdown" | "image" | "diff";

export interface Artifact {
  id: string;
  title: string;
  type: ArtifactType;
  language?: string;
  content: string;
  originalContent?: string; // for diff view
  createdAt: string;
  size?: string;
}

// ─── Mock artifacts ───────────────────────────────────────────────────────────

export const DEMO_ARTIFACTS: Artifact[] = [
  {
    id: "a1",
    title: "landing.html",
    type: "html",
    content: `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dream Avto — Автосалон</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; background: #f8f9fa; color: #1a1a2e; }
    .hero { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); color: white; padding: 60px 40px; text-align: center; }
    .hero h1 { font-size: 42px; font-weight: 800; margin-bottom: 12px; }
    .hero p { font-size: 18px; opacity: 0.8; margin-bottom: 28px; }
    .btn { display: inline-block; background: #e94560; color: white; padding: 14px 32px; border-radius: 8px; font-weight: 700; text-decoration: none; font-size: 16px; }
    .cars { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; padding: 40px; }
    .car-card { background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
    .car-img { height: 160px; background: linear-gradient(135deg, #667eea, #764ba2); display: flex; align-items: center; justify-content: center; font-size: 48px; }
    .car-info { padding: 16px; }
    .car-name { font-size: 16px; font-weight: 700; margin-bottom: 4px; }
    .car-price { font-size: 20px; font-weight: 800; color: #e94560; }
    .car-meta { font-size: 12px; color: #666; margin-top: 4px; }
  </style>
</head>
<body>
  <div class="hero">
    <h1>Dream Avto</h1>
    <p>Лучшие автомобили по лучшим ценам в Москве</p>
    <a href="#catalog" class="btn">Смотреть каталог</a>
  </div>
  <div id="catalog" class="cars">
    <div class="car-card">
      <div class="car-img">🚗</div>
      <div class="car-info">
        <div class="car-name">Toyota Camry 2024</div>
        <div class="car-price">2 890 000 ₽</div>
        <div class="car-meta">2.5L · Автомат · Белый</div>
      </div>
    </div>
    <div class="car-card">
      <div class="car-img">🚙</div>
      <div class="car-info">
        <div class="car-name">BMW X5 2023</div>
        <div class="car-price">7 450 000 ₽</div>
        <div class="car-meta">3.0L · Автомат · Чёрный</div>
      </div>
    </div>
    <div class="car-card">
      <div class="car-img">🏎️</div>
      <div class="car-info">
        <div class="car-name">Mercedes C-Class 2024</div>
        <div class="car-price">5 120 000 ₽</div>
        <div class="car-meta">2.0L · Автомат · Серебро</div>
      </div>
    </div>
  </div>
</body>
</html>`,
    createdAt: "2 мин назад",
    size: "2.1 KB",
  },
  {
    id: "a2",
    title: "nginx.conf",
    type: "code",
    language: "nginx",
    content: `server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name example.com www.example.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=31536000" always;

    root /var/www/html/bitrix;
    index index.php index.html;

    # PHP-FPM
    location ~ \\.php$ {
        fastcgi_pass unix:/var/run/php/php8.2-fpm.sock;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }

    # Static files
    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;
    gzip_min_length 256;
}`,
    createdAt: "5 мин назад",
    size: "1.4 KB",
    originalContent: `server {
    listen 80;
    server_name example.com;

    root /var/www/html;
    index index.php index.html;

    location ~ \\.php$ {
        fastcgi_pass 127.0.0.1:9000;
        fastcgi_index index.php;
        include fastcgi_params;
    }
}`,
  },
  {
    id: "a3",
    title: "README.md",
    type: "markdown",
    content: `# Bitrix CMS — Установка и настройка

## Обзор

Данный проект содержит полную конфигурацию для установки 1С-Битрикс на Ubuntu 22.04 с nginx, PHP 8.2 и MySQL 8.0.

## Требования

- Ubuntu 22.04 LTS
- Минимум 2 GB RAM
- 20 GB свободного места
- Домен с настроенными DNS записями

## Установка

### 1. Обновление системы

\`\`\`bash
apt update && apt upgrade -y
\`\`\`

### 2. Установка PHP 8.2

\`\`\`bash
add-apt-repository ppa:ondrej/php
apt install php8.2-fpm php8.2-mysql php8.2-curl php8.2-gd -y
\`\`\`

### 3. Настройка MySQL

\`\`\`sql
CREATE DATABASE bitrix_db CHARACTER SET utf8mb4;
CREATE USER 'bitrix_user'@'localhost' IDENTIFIED BY 'secure_password';
GRANT ALL ON bitrix_db.* TO 'bitrix_user'@'localhost';
\`\`\`

## Структура файлов

\`\`\`
/var/www/html/bitrix/
├── bitrix/          # Ядро Битрикс
├── upload/          # Загруженные файлы
├── local/           # Кастомизации
└── index.php        # Точка входа
\`\`\`

## Статус установки

| Компонент | Версия | Статус |
|-----------|--------|--------|
| PHP | 8.2.15 | ✅ Установлен |
| MySQL | 8.0.36 | ✅ Установлен |
| Nginx | 1.24.0 | ✅ Настроен |
| SSL | Let's Encrypt | ✅ Активен |
| Redis | 7.2.4 | ✅ Работает |`,
    createdAt: "8 мин назад",
    size: "1.8 KB",
  },
];

// ─── Syntax highlighting (simple) ────────────────────────────────────────────

function highlightCode(code: string, lang?: string): string {
  if (!lang) return escapeHtml(code);
  const escaped = escapeHtml(code);

  if (lang === "nginx" || lang === "bash" || lang === "shell") {
    return escaped
      .replace(/(#[^\n]*)/g, '<span style="color:#6a9955">$1</span>')
      .replace(/\b(server|location|listen|server_name|root|index|ssl_certificate|add_header|gzip|return|include|fastcgi_pass|fastcgi_param|expires)\b/g, '<span style="color:#569cd6">$1</span>')
      .replace(/("[^"]*")/g, '<span style="color:#ce9178">$1</span>')
      .replace(/\b(\d+)\b/g, '<span style="color:#b5cea8">$1</span>');
  }

  if (lang === "sql") {
    return escaped
      .replace(/\b(CREATE|DATABASE|USER|GRANT|ALL|ON|TO|IDENTIFIED|BY|CHARACTER|SET)\b/g, '<span style="color:#569cd6">$1</span>')
      .replace(/('[^']*')/g, '<span style="color:#ce9178">$1</span>');
  }

  return escaped
    .replace(/(\/\/[^\n]*|#[^\n]*)/g, '<span style="color:#6a9955">$1</span>')
    .replace(/\b(const|let|var|function|return|import|export|from|if|else|for|while|class|interface|type|extends|implements)\b/g, '<span style="color:#569cd6">$1</span>')
    .replace(/("[^"]*"|'[^']*'|`[^`]*`)/g, '<span style="color:#ce9178">$1</span>');
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ─── Diff renderer ────────────────────────────────────────────────────────────

function renderDiff(original: string, modified: string) {
  const origLines = original.split("\n");
  const modLines = modified.split("\n");
  const result: { type: "add" | "remove" | "same"; line: string }[] = [];

  // Simple LCS-based diff (line level)
  const maxLen = Math.max(origLines.length, modLines.length);
  let oi = 0, mi = 0;
  while (oi < origLines.length || mi < modLines.length) {
    if (oi >= origLines.length) {
      result.push({ type: "add", line: modLines[mi++] });
    } else if (mi >= modLines.length) {
      result.push({ type: "remove", line: origLines[oi++] });
    } else if (origLines[oi] === modLines[mi]) {
      result.push({ type: "same", line: origLines[oi] });
      oi++; mi++;
    } else {
      result.push({ type: "remove", line: origLines[oi++] });
      result.push({ type: "add", line: modLines[mi++] });
    }
  }
  return result;
}

// ─── Markdown renderer (simple) ──────────────────────────────────────────────

function renderMarkdown(md: string): string {
  return md
    .replace(/^### (.+)$/gm, '<h3 style="font-size:14px;font-weight:700;margin:16px 0 6px;color:#1a1a2e">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 style="font-size:16px;font-weight:700;margin:20px 0 8px;color:#1a1a2e;border-bottom:1px solid #e5e7eb;padding-bottom:4px">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 style="font-size:20px;font-weight:800;margin:0 0 12px;color:#1a1a2e">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code style="background:#f3f4f6;padding:1px 5px;border-radius:3px;font-size:11px;font-family:monospace">$1</code>')
    .replace(/```[\w]*\n([\s\S]*?)```/g, '<pre style="background:#1e1e2e;color:#cdd6f4;padding:12px;border-radius:8px;font-size:11px;overflow-x:auto;margin:8px 0"><code>$1</code></pre>')
    .replace(/^\| (.+) \|$/gm, (_, row) => {
      const cells = row.split(" | ").map((c: string) => `<td style="padding:4px 8px;border:1px solid #e5e7eb;font-size:12px">${c}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .replace(/(<tr>.*<\/tr>\n?)+/g, m => `<table style="border-collapse:collapse;margin:8px 0;width:100%">${m}</table>`)
    .replace(/^- (.+)$/gm, '<li style="margin-left:16px;font-size:13px;margin-bottom:2px">$1</li>')
    .replace(/\n\n/g, '</p><p style="margin-bottom:8px;font-size:13px;line-height:1.6">')
    .replace(/^(?!<[h|l|p|t|u|o|c|p])(.+)$/gm, '<p style="margin-bottom:8px;font-size:13px;line-height:1.6">$1</p>');
}

// ─── ArtifactViewer ───────────────────────────────────────────────────────────

type ViewMode = "preview" | "code" | "diff" | "split";

interface ArtifactViewerProps {
  artifact: Artifact;
  onClose?: () => void;
  className?: string;
}

export function ArtifactViewer({ artifact, onClose, className }: ArtifactViewerProps) {
  const [mode, setMode] = useState<ViewMode>(artifact.type === "html" ? "preview" : artifact.type === "code" ? "code" : "preview");
  const [editedContent, setEditedContent] = useState(artifact.content);
  const [isEditing, setIsEditing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const isDirty = editedContent !== artifact.content;

  const handleCopy = () => {
    navigator.clipboard.writeText(editedContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success("Скопировано в буфер обмена");
  };

  const handleDownload = () => {
    const blob = new Blob([editedContent], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = artifact.title;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Файл ${artifact.title} скачан`);
  };

  const handleReset = () => {
    setEditedContent(artifact.content);
    toast.info("Изменения отменены");
  };

  const handleSave = () => {
    setIsEditing(false);
    toast.success("Изменения сохранены");
  };

  const typeIcon = {
    html:     <Globe size={12} className="text-orange-500" />,
    code:     <FileCode size={12} className="text-blue-500" />,
    markdown: <FileText size={12} className="text-green-500" />,
    image:    <ImageIcon size={12} className="text-purple-500" />,
    diff:     <Diff size={12} className="text-amber-500" />,
  }[artifact.type];

  const canPreview = artifact.type === "html" || artifact.type === "markdown";
  const canDiff = !!artifact.originalContent;

  const diffLines = canDiff ? renderDiff(artifact.originalContent!, editedContent) : [];
  const added = diffLines.filter(l => l.type === "add").length;
  const removed = diffLines.filter(l => l.type === "remove").length;

  return (
    <div className={cn(
      "flex flex-col bg-white dark:bg-[#0f1117] border border-[#E8E6E1] dark:border-[#2a2d3a] rounded-xl overflow-hidden",
      isFullscreen && "fixed inset-4 z-50 shadow-2xl",
      className
    )}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#E8E6E1] dark:border-[#2a2d3a] bg-[#F8F7F5] dark:bg-[#1a1d2e] shrink-0">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          {typeIcon}
          <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 truncate">{artifact.title}</span>
          {artifact.size && (
            <span className="text-[10px] text-gray-400 shrink-0">{artifact.size}</span>
          )}
          {isDirty && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 shrink-0">изменён</span>
          )}
        </div>

        {/* View mode toggles */}
        <div className="flex items-center gap-0.5 bg-gray-100 dark:bg-[#2a2d3a] rounded-md p-0.5">
          {canPreview && (
            <button
              onClick={() => setMode("preview")}
              className={cn(
                "flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors",
                mode === "preview" ? "bg-white dark:bg-[#0f1117] text-gray-800 dark:text-gray-200 shadow-sm" : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              )}
            >
              <Eye size={10} />
              Превью
            </button>
          )}
          <button
            onClick={() => setMode("code")}
            className={cn(
              "flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors",
              mode === "code" ? "bg-white dark:bg-[#0f1117] text-gray-800 dark:text-gray-200 shadow-sm" : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            )}
          >
            <Code2 size={10} />
            Код
          </button>
          {canDiff && (
            <button
              onClick={() => setMode("diff")}
              className={cn(
                "flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors",
                mode === "diff" ? "bg-white dark:bg-[#0f1117] text-gray-800 dark:text-gray-200 shadow-sm" : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              )}
            >
              <Diff size={10} />
              Diff
              {(added > 0 || removed > 0) && (
                <span className="text-[9px] text-green-600">+{added}</span>
              )}
            </button>
          )}
          {canPreview && (
            <button
              onClick={() => setMode("split")}
              className={cn(
                "flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors",
                mode === "split" ? "bg-white dark:bg-[#0f1117] text-gray-800 dark:text-gray-200 shadow-sm" : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              )}
            >
              <Split size={10} />
              Split
            </button>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-0.5">
          {mode === "code" && !isEditing && (
            <button
              onClick={() => setIsEditing(true)}
              className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
              title="Редактировать"
            >
              <Pencil size={11} className="text-gray-500" />
            </button>
          )}
          {isEditing && (
            <>
              <button
                onClick={handleReset}
                className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
                title="Отменить изменения"
              >
                <RotateCcw size={11} className="text-gray-500" />
              </button>
              <button
                onClick={handleSave}
                className="flex items-center gap-1 px-2 py-1 rounded bg-indigo-600 text-white text-[10px] font-medium hover:bg-indigo-700 transition-colors"
              >
                <Save size={9} />
                Сохранить
              </button>
            </>
          )}
          <button
            onClick={handleCopy}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
            title="Копировать"
          >
            {copied ? <Check size={11} className="text-green-500" /> : <Copy size={11} className="text-gray-500" />}
          </button>
          <button
            onClick={handleDownload}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
            title="Скачать"
          >
            <Download size={11} className="text-gray-500" />
          </button>
          <button
            onClick={() => setIsFullscreen(f => !f)}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
          >
            {isFullscreen ? <Minimize2 size={11} className="text-gray-500" /> : <Maximize2 size={11} className="text-gray-500" />}
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-gray-200 dark:hover:bg-[#2a2d3a] transition-colors"
            >
              <X size={11} className="text-gray-500" />
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {/* Preview mode */}
        {mode === "preview" && artifact.type === "html" && (
          <iframe
            ref={iframeRef}
            srcDoc={editedContent}
            className="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin"
            title={artifact.title}
          />
        )}

        {mode === "preview" && artifact.type === "markdown" && (
          <div
            className="p-4 overflow-auto h-full prose prose-sm max-w-none"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(editedContent) }}
          />
        )}

        {/* Code mode */}
        {mode === "code" && (
          <div className="h-full overflow-auto bg-[#1e1e2e] dark:bg-[#0a0a14]">
            {isEditing ? (
              <textarea
                value={editedContent}
                onChange={e => setEditedContent(e.target.value)}
                className="w-full h-full bg-transparent text-[#cdd6f4] font-mono text-[11px] p-4 outline-none resize-none leading-relaxed"
                spellCheck={false}
              />
            ) : (
              <pre className="p-4 text-[11px] font-mono leading-relaxed overflow-auto">
                <code
                  dangerouslySetInnerHTML={{
                    __html: highlightCode(editedContent, artifact.language)
                  }}
                />
              </pre>
            )}
          </div>
        )}

        {/* Diff mode */}
        {mode === "diff" && canDiff && (
          <div className="h-full overflow-auto bg-[#1e1e2e]">
            <div className="flex items-center gap-4 px-4 py-2 bg-[#161622] border-b border-[#2a2d3a] text-[10px]">
              <span className="text-red-400">− {removed} удалено</span>
              <span className="text-green-400">+ {added} добавлено</span>
            </div>
            <pre className="p-4 text-[11px] font-mono leading-relaxed">
              {diffLines.map((line, i) => (
                <div
                  key={i}
                  className={cn(
                    "px-2 -mx-2",
                    line.type === "add" && "bg-green-900/30 text-green-300",
                    line.type === "remove" && "bg-red-900/30 text-red-300",
                    line.type === "same" && "text-gray-400"
                  )}
                >
                  <span className="select-none mr-3 opacity-50 w-4 inline-block">
                    {line.type === "add" ? "+" : line.type === "remove" ? "−" : " "}
                  </span>
                  {escapeHtml(line.line)}
                </div>
              ))}
            </pre>
          </div>
        )}

        {/* Split mode */}
        {mode === "split" && canPreview && (
          <div className="flex h-full">
            <div className="flex-1 overflow-auto bg-[#1e1e2e] border-r border-[#2a2d3a]">
              <div className="px-3 py-1.5 bg-[#161622] border-b border-[#2a2d3a] text-[10px] text-gray-400 flex items-center gap-1">
                <Code2 size={9} />
                Код
              </div>
              <textarea
                value={editedContent}
                onChange={e => setEditedContent(e.target.value)}
                className="w-full h-[calc(100%-28px)] bg-transparent text-[#cdd6f4] font-mono text-[11px] p-3 outline-none resize-none leading-relaxed"
                spellCheck={false}
              />
            </div>
            <div className="flex-1 overflow-hidden">
              <div className="px-3 py-1.5 bg-gray-50 dark:bg-[#1a1d2e] border-b border-[#E8E6E1] dark:border-[#2a2d3a] text-[10px] text-gray-400 flex items-center gap-1">
                <Eye size={9} />
                Превью
              </div>
              {artifact.type === "html" ? (
                <iframe
                  srcDoc={editedContent}
                  className="w-full h-[calc(100%-28px)] border-0"
                  sandbox="allow-scripts allow-same-origin"
                  title="preview"
                />
              ) : (
                <div
                  className="p-3 overflow-auto h-[calc(100%-28px)] text-sm"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(editedContent) }}
                />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 border-t border-[#E8E6E1] dark:border-[#2a2d3a] bg-[#F8F7F5] dark:bg-[#1a1d2e] px-3 py-1.5 flex items-center gap-3">
        <span className="text-[10px] text-gray-400">{artifact.type.toUpperCase()}</span>
        {artifact.language && (
          <span className="text-[10px] text-gray-400">{artifact.language}</span>
        )}
        <span className="text-[10px] text-gray-400 ml-auto">{artifact.createdAt}</span>
        {artifact.type === "html" && (
          <button
            onClick={() => {
              const w = window.open("", "_blank");
              if (w) { w.document.write(editedContent); w.document.close(); }
            }}
            className="flex items-center gap-1 text-[10px] text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            <ExternalLink size={9} />
            Открыть
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Artifact List (for sidebar/panel) ───────────────────────────────────────

interface ArtifactListProps {
  artifacts: Artifact[];
  onSelect: (artifact: Artifact) => void;
  selectedId?: string;
}

export function ArtifactList({ artifacts, onSelect, selectedId }: ArtifactListProps) {
  const typeIcon = (type: ArtifactType) => ({
    html:     <Globe size={12} className="text-orange-500" />,
    code:     <FileCode size={12} className="text-blue-500" />,
    markdown: <FileText size={12} className="text-green-500" />,
    image:    <ImageIcon size={12} className="text-purple-500" />,
    diff:     <Diff size={12} className="text-amber-500" />,
  }[type]);

  if (artifacts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-32 text-center px-4">
        <File size={24} className="text-gray-200 dark:text-gray-700 mb-2" />
        <div className="text-xs text-gray-400">Агент ещё не создал артефактов</div>
      </div>
    );
  }

  return (
    <div className="p-2 space-y-1">
      {artifacts.map(artifact => (
        <button
          key={artifact.id}
          onClick={() => onSelect(artifact)}
          className={cn(
            "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-left transition-colors",
            selectedId === artifact.id
              ? "bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-100 dark:border-indigo-900/50"
              : "hover:bg-gray-50 dark:hover:bg-[#1a1d2e]"
          )}
        >
          <div className="shrink-0">{typeIcon(artifact.type)}</div>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate">{artifact.title}</div>
            <div className="text-[10px] text-gray-400">{artifact.createdAt} · {artifact.size}</div>
          </div>
          <ChevronRight size={11} className="text-gray-300 shrink-0" />
        </button>
      ))}
    </div>
  );
}
