// useProjectTask.ts — Hook for submitting tasks to the Orchestrator pipeline
// and tracking real-time progress via WebSocket

import { useState, useCallback, useRef, useEffect } from "react";
import { api, ProjectState, RunResult, TaskMode } from "@/lib/api";
import type { RunProgress, PipelineStatus } from "@/components/arcane/OrchestratorProgress";

export type { TaskMode };

export interface UseProjectTaskOptions {
  /** If provided, use this project instead of auto-creating one */
  projectId?: string;
  onDone?: (result: RunProgress) => void;
  onError?: (error: string) => void;
}

export interface UseProjectTaskReturn {
  isRunning: boolean;
  progress: RunProgress | null;
  project: ProjectState | null;
  error: string | null;
  submitTask: (task: string, mode?: TaskMode, budgetLimit?: number) => Promise<void>;
  cancelTask: () => Promise<void>;
  reset: () => void;
}

const DEFAULT_PROJECT_NAME = "Arcane Project";

export function useProjectTask(options: UseProjectTaskOptions = {}): UseProjectTaskReturn {
  const { projectId: externalProjectId, onDone, onError } = options;

  const [project, setProject] = useState<ProjectState | null>(null);
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const currentRunIdRef = useRef<string | null>(null);
  const doneCalledRef = useRef(false);

  useEffect(() => {
    return () => { wsRef.current?.close(); };
  }, []);

  const handleWSEvent = useCallback((event: Record<string, unknown>) => {
    const type = event.type as string;
    const status = event.status as string;

    setProgress(prev => {
      if (!prev) return prev;
      const next = { ...prev };

      if (type === "run_status") {
        const data = (event.data ?? event) as Record<string, unknown>;

        if (event.run_id) next.run_id = event.run_id as string;
        if (data.task_type) next.task_type = data.task_type as string;
        if (data.mode) next.mode = data.mode as string;
        if (data.team) next.team = data.team as Record<string, string>;
        if (data.cost_total !== undefined) next.cost_total = data.cost_total as number;
        if (data.error) next.error = data.error as string;
        if (data.result_url) next.result_url = data.result_url as string;
        if (data.manus_task_id) next.manus_task_id = data.manus_task_id as string;
        if (data.manus_status) next.manus_status = data.manus_status as string;
        if (data.manus_url) next.manus_url = data.manus_url as string;

        if (status === "specialist_start") {
          const role = data.role as string;
          const model = data.model as string;
          next.specialists = [
            ...prev.specialists.filter(s => s.role !== role),
            { role, model, chars: 0, cost: 0, status: "running" }
          ];
        } else if (status === "specialist_done") {
          const role = data.role as string;
          next.specialists = prev.specialists.map(s =>
            s.role === role
              ? { ...s, chars: (data.chars as number) ?? s.chars, cost: (data.cost as number) ?? s.cost, status: "done" }
              : s
          );
        } else if (status === "specialist_failed") {
          const role = data.role as string;
          next.specialists = prev.specialists.map(s =>
            s.role === role ? { ...s, status: "failed" } : s
          );
        } else if (status === "iteration_start") {
          const num = data.iteration as number;
          next.iterations = [
            ...prev.iterations.filter(i => i.number !== num),
            { number: num, phase: (data.phase as string) ?? "running", status: "running" }
          ];
        } else if (status === "iteration_done") {
          const num = data.iteration as number;
          next.iterations = prev.iterations.map(i =>
            i.number === num
              ? { ...i, phase: (data.phase as string) ?? i.phase, tool: data.tool as string, cost: data.cost as number, status: "done" }
              : i
          );
        } else if (status === "iteration_failed") {
          const num = data.iteration as number;
          next.iterations = prev.iterations.map(i =>
            i.number === num ? { ...i, status: "failed" } : i
          );
        } else if (status === "qa_round") {
          const round = (data.round as number) ?? (prev.qa_rounds.length + 1);
          next.qa_rounds = [
            ...prev.qa_rounds.filter(q => q.round !== round),
            {
              round,
              result: (data.result as string) === "pass" ? "pass" : "fail",
              model: (data.model as string) ?? "",
              notes: data.notes as string
            }
          ];
        }

        if (["running", "done", "failed", "cancelled"].includes(status)) {
          next.status = status as PipelineStatus;
          if (status === "running" && !prev.started_at) next.started_at = Date.now();
          if (["done", "failed", "cancelled"].includes(status)) {
            next.finished_at = Date.now();
          }
        }
      }

      return next;
    });

    if (type === "run_status") {
      if (status === "done" || status === "failed" || status === "cancelled") {
        setIsRunning(false);
        wsRef.current?.close();

        if (!doneCalledRef.current) {
          doneCalledRef.current = true;
          setProgress(finalProgress => {
            if (finalProgress && onDone) onDone(finalProgress);
            return finalProgress;
          });
        }

        if (status === "failed") {
          const errMsg = (event.error as string) ?? "Task failed";
          setError(errMsg);
          if (onError) onError(errMsg);
        }
      }
    }
  }, [onDone, onError]);

  const connectWS = useCallback((pid: string) => {
    wsRef.current?.close();
    const ws = api.projects.connectWS(pid, handleWSEvent);
    wsRef.current = ws;
  }, [handleWSEvent]);

  const submitTask = useCallback(async (task: string, mode: TaskMode = "optimum", budgetLimit?: number) => {
    try {
      setError(null);
      setIsRunning(true);
      doneCalledRef.current = false;

      let pid = externalProjectId ?? project?.id ?? project?.project_id;

      if (!pid) {
        const resp = await api.projects.create(DEFAULT_PROJECT_NAME, undefined, mode, budgetLimit);
        const newProject = resp.project;
        pid = newProject.id ?? newProject.project_id ?? resp.path.split("/").pop()!;
        setProject({ ...newProject, id: pid });
      }

      const initProgress: RunProgress = {
        run_id: "",
        project_id: pid,
        status: "running",
        specialists: [],
        iterations: [],
        qa_rounds: [],
        cost_total: 0,
        started_at: Date.now(),
        mode,
      };
      setProgress(initProgress);

      connectWS(pid);

      const resp = await api.projects.submitTask(pid, task, mode, budgetLimit);
      const run = resp.run;
      currentRunIdRef.current = run.run_id;

      setProgress(prev => prev ? { ...prev, run_id: run.run_id } : prev);

    } catch (err) {
      const msg = err instanceof Error ? err.message : "Error submitting task";
      setError(msg);
      setIsRunning(false);
      if (onError) onError(msg);
    }
  }, [externalProjectId, project, connectWS, onError]);

  const cancelTask = useCallback(async () => {
    const runId = currentRunIdRef.current;
    if (!runId) return;
    try {
      await api.projects.cancelRun(runId);
      setIsRunning(false);
      setProgress(prev => prev ? { ...prev, status: "cancelled", finished_at: Date.now() } : prev);
    } catch (err) {
      console.error("Failed to cancel run:", err);
    }
  }, []);

  const reset = useCallback(() => {
    wsRef.current?.close();
    setProgress(null);
    setIsRunning(false);
    setError(null);
    currentRunIdRef.current = null;
    doneCalledRef.current = false;
  }, []);

  return { isRunning, progress, project, error, submitTask, cancelTask, reset };
}
