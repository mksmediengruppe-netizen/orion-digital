// ORION MarkdownContent — renders rich formatted agent output
// Supports: headings, bold, italic, code blocks, inline code, tables, lists, blockquotes, badges
// Design: "Warm Intelligence" — warm off-white, indigo accent

import { cn } from "@/lib/utils";
import { Copy, Check } from "lucide-react";
import { useState } from "react";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

// ─── Token types ─────────────────────────────────────────────────────────────

type Token =
  | { type: "heading"; level: 1 | 2 | 3; text: string }
  | { type: "paragraph"; text: string }
  | { type: "codeblock"; lang: string; code: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "blockquote"; text: string }
  | { type: "hr" }
  | { type: "badge"; label: string; badgeVariant: "success" | "warning" | "error" | "info" | "neutral" };

// ─── Inline renderer ─────────────────────────────────────────────────────────

function renderInline(text: string): React.ReactNode {
  // Split by inline code, bold, italic, links
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    // Inline code `...`
    const codeMatch = remaining.match(/^(.*?)`([^`]+)`([\.\s\S]*)/);
    if (codeMatch) {
      if (codeMatch[1]) parts.push(<span key={key++}>{renderInlineBasic(codeMatch[1])}</span>);
      parts.push(
        <code key={key++} className="px-1.5 py-0.5 rounded bg-gray-100 border border-gray-200 text-[12px] font-mono text-rose-600">
          {codeMatch[2]}
        </code>
      );
      remaining = codeMatch[3];
      continue;
    }
    // Bold **...**
    const boldMatch = remaining.match(/^(.*?)\*\*([^*]+)\*\*([\s\S]*)/);
    if (boldMatch) {
      if (boldMatch[1]) parts.push(<span key={key++}>{renderInlineBasic(boldMatch[1])}</span>);
      parts.push(<strong key={key++} className="font-semibold text-gray-900">{boldMatch[2]}</strong>);
      remaining = boldMatch[3];
      continue;
    }
    // Italic *...*
    const italicMatch = remaining.match(/^(.*?)\*([^*]+)\*([\s\S]*)/);
    if (italicMatch) {
      if (italicMatch[1]) parts.push(<span key={key++}>{renderInlineBasic(italicMatch[1])}</span>);
      parts.push(<em key={key++} className="italic text-gray-700">{italicMatch[2]}</em>);
      remaining = italicMatch[3];
      continue;
    }
    // URL [text](url)
    const linkMatch = remaining.match(/^(.*?)\[([^\]]+)\]\(([^)]+)\)([\s\S]*)/);
    if (linkMatch) {
      if (linkMatch[1]) parts.push(<span key={key++}>{renderInlineBasic(linkMatch[1])}</span>);
      parts.push(
        <a key={key++} href={linkMatch[3]} target="_blank" rel="noopener noreferrer" className="text-indigo-600 underline underline-offset-2 hover:text-indigo-800 transition-colors">
          {linkMatch[2]}
        </a>
      );
      remaining = linkMatch[4];
      continue;
    }
    // No more patterns — render rest
    parts.push(<span key={key++}>{renderInlineBasic(remaining)}</span>);
    break;
  }
  return parts.length === 1 ? parts[0] : <>{parts}</>;
}

function renderInlineBasic(text: string): React.ReactNode {
  return text;
}

// ─── Parser ───────────────────────────────────────────────────────────────────

function parseMarkdown(content: string): Token[] {
  const tokens: Token[] = [];
  const lines = content.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Skip empty lines
    if (line.trim() === "") { i++; continue; }

    // Code block ```lang
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim() || "text";
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      tokens.push({ type: "codeblock", lang, code: codeLines.join("\n") });
      continue;
    }

    // Headings
    if (line.startsWith("### ")) { tokens.push({ type: "heading", level: 3, text: line.slice(4) }); i++; continue; }
    if (line.startsWith("## ")) { tokens.push({ type: "heading", level: 2, text: line.slice(3) }); i++; continue; }
    if (line.startsWith("# ")) { tokens.push({ type: "heading", level: 1, text: line.slice(2) }); i++; continue; }

    // HR
    if (line.match(/^---+$/) || line.match(/^\*\*\*+$/)) { tokens.push({ type: "hr" }); i++; continue; }

    // Blockquote
    if (line.startsWith("> ")) {
      const quoteLines: string[] = [line.slice(2)];
      i++;
      while (i < lines.length && lines[i].startsWith("> ")) {
        quoteLines.push(lines[i].slice(2));
        i++;
      }
      tokens.push({ type: "blockquote", text: quoteLines.join("\n") });
      continue;
    }

    // Table (detect by | ... | pattern)
    if (line.includes("|") && line.trim().startsWith("|")) {
      const tableLines: string[] = [line];
      i++;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim().startsWith("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      if (tableLines.length >= 2) {
        const headers = tableLines[0].split("|").map(c => c.trim()).filter(Boolean);
        const rows: string[][] = [];
        for (let r = 2; r < tableLines.length; r++) {
          const cells = tableLines[r].split("|").map(c => c.trim()).filter(Boolean);
          if (cells.length > 0) rows.push(cells);
        }
        tokens.push({ type: "table", headers, rows });
        continue;
      }
    }

    // Unordered list
    if (line.match(/^[-*+] /)) {
      const items: string[] = [line.slice(2)];
      i++;
      while (i < lines.length && lines[i].match(/^[-*+] /)) {
        items.push(lines[i].slice(2));
        i++;
      }
      tokens.push({ type: "ul", items });
      continue;
    }

    // Ordered list
    if (line.match(/^\d+\. /)) {
      const items: string[] = [line.replace(/^\d+\. /, "")];
      i++;
      while (i < lines.length && lines[i].match(/^\d+\. /)) {
        items.push(lines[i].replace(/^\d+\. /, ""));
        i++;
      }
      tokens.push({ type: "ol", items });
      continue;
    }

    // Badge shorthand :::success text:::
    const badgeMatch = line.match(/^:::(success|warning|error|info|neutral) (.+):::$/);
    if (badgeMatch) {
      tokens.push({ type: "badge", label: badgeMatch[2], badgeVariant: badgeMatch[1] as "success" | "warning" | "error" | "info" | "neutral" });
      i++;
      continue;
    }

    // Paragraph — collect until blank line
    const paraLines: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !lines[i].startsWith("#") && !lines[i].startsWith("```") && !lines[i].startsWith("|") && !lines[i].match(/^[-*+] /) && !lines[i].match(/^\d+\. /)) {
      paraLines.push(lines[i]);
      i++;
    }
    tokens.push({ type: "paragraph", text: paraLines.join(" ") });
  }

  return tokens;
}

// ─── Code block with copy ─────────────────────────────────────────────────────

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden my-3 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-900 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/70" />
            <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/70" />
            <span className="w-2.5 h-2.5 rounded-full bg-green-500/70" />
          </div>
          <span className="text-[11px] text-gray-400 font-mono">{lang}</span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200 transition-colors"
        >
          {copied ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
          {copied ? "Скопировано" : "Копировать"}
        </button>
      </div>
      {/* Code */}
      <pre className="bg-gray-950 px-4 py-3 overflow-x-auto text-[12px] leading-relaxed">
        <code className="text-gray-200 font-mono">{code}</code>
      </pre>
    </div>
  );
}

// ─── Badge ────────────────────────────────────────────────────────────────────

const BADGE_STYLES = {
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warning: "bg-amber-50 text-amber-700 border-amber-200",
  error:   "bg-red-50 text-red-700 border-red-200",
  info:    "bg-blue-50 text-blue-700 border-blue-200",
  neutral: "bg-gray-50 text-gray-600 border-gray-200",
};

// ─── Main renderer ────────────────────────────────────────────────────────────

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  const tokens = parseMarkdown(content);

  return (
    <div className={cn("text-sm text-gray-800 leading-relaxed space-y-2", className)}>
      {tokens.map((token, i) => {
        switch (token.type) {
          case "heading":
            return token.level === 1 ? (
              <h1 key={i} className="text-lg font-bold text-gray-900 mt-3 mb-1 leading-tight">{renderInline(token.text)}</h1>
            ) : token.level === 2 ? (
              <h2 key={i} className="text-base font-semibold text-gray-900 mt-3 mb-1 leading-tight border-b border-gray-100 pb-1">{renderInline(token.text)}</h2>
            ) : (
              <h3 key={i} className="text-sm font-semibold text-gray-800 mt-2 mb-0.5">{renderInline(token.text)}</h3>
            );

          case "paragraph":
            return <p key={i} className="text-gray-700 leading-relaxed">{renderInline(token.text)}</p>;

          case "codeblock":
            return <CodeBlock key={i} lang={token.lang} code={token.code} />;

          case "table":
            return (
              <div key={i} className="overflow-x-auto rounded-lg border border-gray-200 my-3">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      {token.headers.map((h, j) => (
                        <th key={j} className="px-3 py-2 text-left font-semibold text-gray-700 whitespace-nowrap">
                          {renderInline(h)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {token.rows.map((row, ri) => (
                      <tr key={ri} className={cn("border-b border-gray-100 last:border-0", ri % 2 === 1 && "bg-gray-50/50")}>
                        {row.map((cell, ci) => (
                          <td key={ci} className="px-3 py-2 text-gray-700 align-top">
                            {renderInline(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );

          case "ul":
            return (
              <ul key={i} className="space-y-1 pl-1">
                {token.items.map((item, j) => (
                  <li key={j} className="flex items-start gap-2 text-gray-700">
                    <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-indigo-400 shrink-0" />
                    <span>{renderInline(item)}</span>
                  </li>
                ))}
              </ul>
            );

          case "ol":
            return (
              <ol key={i} className="space-y-1 pl-1">
                {token.items.map((item, j) => (
                  <li key={j} className="flex items-start gap-2.5 text-gray-700">
                    <span className="shrink-0 w-5 h-5 rounded-full bg-indigo-50 border border-indigo-200 text-indigo-700 text-[10px] font-semibold flex items-center justify-center mt-0.5">
                      {j + 1}
                    </span>
                    <span className="pt-0.5">{renderInline(item)}</span>
                  </li>
                ))}
              </ol>
            );

          case "blockquote":
            return (
              <blockquote key={i} className="border-l-3 border-indigo-300 pl-3 py-1 bg-indigo-50/50 rounded-r-lg text-indigo-800 italic text-sm">
                {renderInline(token.text)}
              </blockquote>
            );

          case "hr":
            return <hr key={i} className="border-gray-200 my-2" />;

          case "badge":
            return (
              <div key={i} className={cn("inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium", BADGE_STYLES[token.badgeVariant])}>
                {token.badgeVariant === "success" && "✓"}
                {token.badgeVariant === "warning" && "⚠"}
                {token.badgeVariant === "error" && "✗"}
                {token.badgeVariant === "info" && "ℹ"}
                {token.label}
              </div>
            );

          default:
            return null;
        }
      })}
    </div>
  );
}
