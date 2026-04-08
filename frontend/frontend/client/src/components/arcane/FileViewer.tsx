// FileViewer — inline code/text viewer with syntax highlighting (highlight.js)
// Design: dark panel, monospace font, line numbers, copy button, close button
// Used inside RightPanel Artifacts tab when user clicks a file row

import { useEffect, useRef, useState, useCallback } from "react";
import { X, Copy, Check, Download, Loader2 } from "lucide-react";
import hljs from "highlight.js";

// ── Highlight.js dark theme injected once ──────────────────────────────────
const HLJS_THEME = `
.hljs{background:#0d1117;color:#e6edf3}
.hljs-doctag,.hljs-keyword,.hljs-meta .hljs-keyword,.hljs-template-tag,.hljs-template-variable,.hljs-type,.hljs-variable.language_{color:#ff7b72}
.hljs-title,.hljs-title.class_,.hljs-title.class_.inherited__,.hljs-title.function_{color:#d2a8ff}
.hljs-attr,.hljs-attribute,.hljs-literal,.hljs-meta,.hljs-number,.hljs-operator,.hljs-selector-attr,.hljs-selector-class,.hljs-selector-id,.hljs-variable{color:#79c0ff}
.hljs-meta .hljs-string,.hljs-regexp,.hljs-string{color:#a5d6ff}
.hljs-built_in,.hljs-symbol{color:#ffa657}
.hljs-code,.hljs-comment,.hljs-formula{color:#8b949e}
.hljs-name,.hljs-quote,.hljs-selector-pseudo,.hljs-selector-tag{color:#7ee787}
.hljs-subst{color:#e6edf3}
.hljs-section{color:#1f6feb;font-weight:700}
.hljs-bullet{color:#f2cc60}
.hljs-emphasis{color:#e6edf3;font-style:italic}
.hljs-strong{color:#e6edf3;font-weight:700}
.hljs-addition{color:#aff5b4;background-color:#033a16}
.hljs-deletion{color:#ffdcd7;background-color:#67060c}
`;

let themeInjected = false;
function injectTheme() {
  if (themeInjected) return;
  const style = document.createElement("style");
  style.textContent = HLJS_THEME;
  document.head.appendChild(style);
  themeInjected = true;
}

// ── Language detection by file extension ──────────────────────────────────
function langFromPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  const MAP: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", html: "xml", htm: "xml", css: "css", scss: "css",
    json: "json", md: "markdown", sh: "bash", bash: "bash",
    yaml: "yaml", yml: "yaml", toml: "ini", ini: "ini",
    sql: "sql", rs: "rust", go: "go", java: "java", cpp: "cpp",
    c: "c", cs: "csharp", rb: "ruby", php: "php", swift: "swift",
    kt: "kotlin", r: "r", txt: "plaintext",
  };
  return MAP[ext] || "plaintext";
}

// ── Props ──────────────────────────────────────────────────────────────────
interface FileViewerProps {
  projectId: string;
  filePath: string;      // relative path, e.g. "index.html"
  fileName: string;
  onClose: () => void;
  downloadUrl: string;
}

export default function FileViewer({ projectId, filePath, fileName, onClose, downloadUrl }: FileViewerProps) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const codeRef = useRef<HTMLElement>(null);

  // Inject theme once
  useEffect(() => { injectTheme(); }, []);

  // Fetch file content
  useEffect(() => {
    setContent(null);
    setError(null);
    fetch(`/api/projects/${projectId}/files/${filePath}`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then(text => setContent(text))
      .catch(e => setError(e.message || "Не удалось загрузить файл"));
  }, [projectId, filePath]);

  // Apply syntax highlighting after content loads
  useEffect(() => {
    if (content !== null && codeRef.current) {
      const lang = langFromPath(filePath);
      try {
        const result = lang === "plaintext"
          ? { value: escapeHtml(content) }
          : hljs.highlight(content, { language: lang, ignoreIllegals: true });
        codeRef.current.innerHTML = result.value;
      } catch {
        codeRef.current.textContent = content;
      }
    }
  }, [content, filePath]);

  const handleCopy = useCallback(() => {
    if (!content) return;
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [content]);

  const lineCount = content ? content.split("\n").length : 0;

  return (
    <div className="flex flex-col h-full bg-[#0d1117] overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 flex-shrink-0 bg-[#161b22]">
        <span className="flex-1 text-[11px] text-[#8b949e] font-mono truncate" title={filePath}>
          {fileName}
        </span>
        {content !== null && (
          <span className="text-[10px] text-[#8b949e]/60 flex-shrink-0">
            {lineCount} {lineCount === 1 ? "строка" : lineCount < 5 ? "строки" : "строк"}
          </span>
        )}
        <div className="flex gap-0.5 flex-shrink-0">
          {content !== null && (
            <button
              onClick={handleCopy}
              className="p-1 rounded hover:bg-white/10 text-[#8b949e] hover:text-white transition-colors"
              title="Скопировать"
            >
              {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
            </button>
          )}
          <a
            href={downloadUrl}
            download={fileName}
            className="p-1 rounded hover:bg-white/10 text-[#8b949e] hover:text-white transition-colors"
            title="Скачать файл"
          >
            <Download size={11} />
          </a>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-white/10 text-[#8b949e] hover:text-white transition-colors"
            title="Закрыть"
          >
            <X size={11} />
          </button>
        </div>
      </div>

      {/* Code area */}
      <div className="flex-1 overflow-auto">
        {error ? (
          <div className="flex flex-col items-center justify-center h-full text-center p-6">
            <span className="text-[12px] text-red-400">{error}</span>
          </div>
        ) : content === null ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 size={18} className="animate-spin text-[#8b949e]" />
          </div>
        ) : (
          <div className="flex text-[11px] font-mono leading-[1.6]">
            {/* Line numbers */}
            <div
              className="select-none text-right pr-3 pl-3 pt-3 pb-3 text-[#8b949e]/40 border-r border-white/5 flex-shrink-0"
              aria-hidden="true"
            >
              {Array.from({ length: lineCount }, (_, i) => (
                <div key={i}>{i + 1}</div>
              ))}
            </div>
            {/* Highlighted code */}
            <pre className="flex-1 overflow-x-auto p-3 m-0 bg-transparent">
              <code ref={codeRef} className={`hljs language-${langFromPath(filePath)}`} />
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

function escapeHtml(s: string) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
