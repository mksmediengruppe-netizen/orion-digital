// OrchestratorProgress.tsx — Real-time orchestrator pipeline progress panel
// Shows specialists, agent iterations, QA rounds, and Manus deployment status

import { useState } from "react";
import { CheckCircle2, Clock, XCircle, Loader2, ChevronDown, ChevronUp, Zap, Users, Bot, Shield, Rocket } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TaskMode } from "@/lib/api";

// ─── Types ────────────────────────────────────────────────────────────────────

export type PipelineStatus = "running" | "done" | "failed" | "cancelled";

export interface SpecialistInfo {
  role: string;
  model: string;
  chars: number;
  cost: number;
  status: "running" | "done" | "failed";
}

export interface IterationInfo {
  number: number;
  phase: string;
  tool?: string;
  cost?: number;
  status: "running" | "done" | "failed";
}

export interface QARoundInfo {
  round: number;
  result: "pass" | "fail";
  model: string;
  notes?: string;
}

export interface RunProgress {
  run_id: string;
  project_id: string;
  status: PipelineStatus;
  task_type?: string;
  mode?: string;
  team?: Record<string, string>;
  specialists: SpecialistInfo[];
  iterations: IterationInfo[];
  qa_rounds: QARoundInfo[];
  cost_total: number;
  started_at?: number;
  finished_at?: number;
  error?: string;
  result_url?: string;
  manus_task_id?: string;
  manus_status?: string;
  manus_url?: string;
}

interface OrchestratorProgressProps {
  progress: RunProgress;
  onCancel?: () => void;
  className?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const ROLE_LABELS: Record<string, string> = {
  art_director: "Art Director",
  writer: "Writer",
  researcher: "Researcher",
  developer: "Developer",
  qa: "QA",
  image_agent: "Image Agent",
};

const MODE_LABELS: Record<string, { label: string; color: string }> = {
  top: { label: "TOP", color: "text-purple-400" },
  optimum: { label: "OPTIMUM", color: "text-blue-400" },
  lite: { label: "LITE", color: "text-green-400" },
  free: { label: "FREE", color: "text-gray-400" },
};

function elapsed(startedAt?: number, finishedAt?: number): string {
  if (!startedAt) return "";
  const ms = (finishedAt ?? Date.now()) - startedAt;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function StatusIcon({ status }: { status: "running" | "done" | "failed" }) {
  if (status === "done") return <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />;
  if (status === "failed") return <XCircle className="w-4 h-4 text-red-400 shrink-0" />;
  return <Loader2 className="w-4 h-4 text-blue-400 animate-spin shrink-0" />;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function OrchestratorProgress({ progress, onCancel, className }: OrchestratorProgressProps) {
  const [showIterations, setShowIterations] = useState(false);
  const modeInfo = MODE_LABELS[progress.mode ?? "optimum"] ?? MODE_LABELS.optimum;
  const isFinished = ["done", "failed", "cancelled"].includes(progress.status);

  return (
    <div className={cn(
      "rounded-xl border border-white/10 bg-white/5 backdrop-blur-sm overflow-hidden",
      className
    )}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-yellow-400" />
          <span className="text-sm font-semibold text-white">Orchestrator Pipeline</span>
          {progress.task_type && (
            <span className="text-xs text-white/40 bg-white/5 px-2 py-0.5 rounded-full">
              {progress.task_type}
            </span>
          )}
          <span className={cn("text-xs font-bold", modeInfo.color)}>{modeInfo.label}</span>
        </div>
        <div className="flex items-center gap-3">
          {progress.cost_total > 0 && (
            <span className="text-xs text-white/50">${progress.cost_total.toFixed(4)}</span>
          )}
          <span className="text-xs text-white/40">{elapsed(progress.started_at, progress.finished_at)}</span>
          {progress.status === "running" && (
            <span className="flex items-center gap-1 text-xs text-blue-400">
              <Loader2 className="w-3 h-3 animate-spin" /> Running
            </span>
          )}
          {progress.status === "done" && (
            <span className="flex items-center gap-1 text-xs text-green-400">
              <CheckCircle2 className="w-3 h-3" /> Done
            </span>
          )}
          {progress.status === "failed" && (
            <span className="flex items-center gap-1 text-xs text-red-400">
              <XCircle className="w-3 h-3" /> Failed
            </span>
          )}
          {!isFinished && onCancel && (
            <button
              onClick={onCancel}
              className="text-xs text-white/30 hover:text-red-400 transition-colors"
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Specialists */}
        {progress.specialists.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Users className="w-3.5 h-3.5 text-white/40" />
              <span className="text-xs font-medium text-white/60 uppercase tracking-wide">Specialists</span>
            </div>
            <div className="grid grid-cols-1 gap-1.5">
              {progress.specialists.map((s) => (
                <div key={s.role} className="flex items-center gap-2 bg-white/5 rounded-lg px-3 py-2">
                  <StatusIcon status={s.status} />
                  <span className="text-sm text-white/80 flex-1">
                    {ROLE_LABELS[s.role] ?? s.role}
                  </span>
                  <span className="text-xs text-white/30">{s.model}</span>
                  {s.chars > 0 && (
                    <span className="text-xs text-white/40">{(s.chars / 1000).toFixed(1)}k chars</span>
                  )}
                  {s.cost > 0 && (
                    <span className="text-xs text-white/30">${s.cost.toFixed(4)}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Agent iterations (collapsible) */}
        {progress.iterations.length > 0 && (
          <div>
            <button
              onClick={() => setShowIterations(v => !v)}
              className="flex items-center gap-2 mb-2 w-full text-left"
            >
              <Bot className="w-3.5 h-3.5 text-white/40" />
              <span className="text-xs font-medium text-white/60 uppercase tracking-wide flex-1">
                Agent ({progress.iterations.length} iterations)
              </span>
              {showIterations
                ? <ChevronUp className="w-3 h-3 text-white/30" />
                : <ChevronDown className="w-3 h-3 text-white/30" />
              }
            </button>
            {showIterations && (
              <div className="grid grid-cols-1 gap-1">
                {progress.iterations.map((it) => (
                  <div key={it.number} className="flex items-center gap-2 bg-white/5 rounded-lg px-3 py-1.5">
                    <StatusIcon status={it.status} />
                    <span className="text-xs text-white/60 w-6">#{it.number}</span>
                    <span className="text-xs text-white/50 flex-1">{it.phase}</span>
                    {it.tool && <span className="text-xs text-white/30">{it.tool}</span>}
                    {it.cost !== undefined && it.cost > 0 && (
                      <span className="text-xs text-white/30">${it.cost.toFixed(4)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* QA Rounds */}
        {progress.qa_rounds.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Shield className="w-3.5 h-3.5 text-white/40" />
              <span className="text-xs font-medium text-white/60 uppercase tracking-wide">QA Review</span>
            </div>
            <div className="grid grid-cols-1 gap-1">
              {progress.qa_rounds.map((q) => (
                <div key={q.round} className="flex items-center gap-2 bg-white/5 rounded-lg px-3 py-1.5">
                  {q.result === "pass"
                    ? <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />
                    : <XCircle className="w-4 h-4 text-orange-400 shrink-0" />
                  }
                  <span className="text-xs text-white/60 flex-1">
                    Round {q.round}: <span className={q.result === "pass" ? "text-green-400" : "text-orange-400"}>{q.result.toUpperCase()}</span>
                  </span>
                  {q.model && <span className="text-xs text-white/30">{q.model}</span>}
                  {q.notes && <span className="text-xs text-white/40 truncate max-w-[200px]">{q.notes}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Manus deployment */}
        {progress.manus_task_id && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Rocket className="w-3.5 h-3.5 text-white/40" />
              <span className="text-xs font-medium text-white/60 uppercase tracking-wide">Manus Deploy</span>
            </div>
            <div className="flex items-center gap-2 bg-white/5 rounded-lg px-3 py-2">
              {progress.manus_status === "completed"
                ? <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />
                : progress.manus_status === "failed"
                  ? <XCircle className="w-4 h-4 text-red-400 shrink-0" />
                  : <Loader2 className="w-4 h-4 text-blue-400 animate-spin shrink-0" />
              }
              <span className="text-xs text-white/60 flex-1">
                {progress.manus_status === "completed" ? "Visual QA passed" : progress.manus_status ?? "Running..."}
              </span>
              {progress.manus_url && (
                <a
                  href={progress.manus_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                >
                  View →
                </a>
              )}
            </div>
          </div>
        )}

        {/* Result URL */}
        {progress.result_url && (
          <div className="flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2">
            <CheckCircle2 className="w-4 h-4 text-green-400 shrink-0" />
            <span className="text-xs text-green-300 flex-1">Task completed</span>
            <a
              href={progress.result_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-green-400 hover:text-green-300 transition-colors font-medium"
            >
              Open result →
            </a>
          </div>
        )}

        {/* Error */}
        {progress.error && (
          <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            <XCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <span className="text-xs text-red-300">{progress.error}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default OrchestratorProgress;
