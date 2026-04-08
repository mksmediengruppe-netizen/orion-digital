// ARCANE StepChip — Manus-style compact pill (inline, not full-width)
// Click opens details in right panel "Steps" tab
import { cn } from "@/lib/utils";
import type { Step } from "@/lib/mockData";
import {
  Terminal, Globe, Search, CheckCircle2, XCircle,
  AlertTriangle, Clock, Loader2, SkipForward,
  FileText, Edit3, Eye, MousePointer, Type, ScrollText,
  Image, Palette, MessageSquare,
  Trash2, Copy, Move, Download, Upload, Archive,
  Server, Database, GitBranch, Package, RefreshCw,
  Play, Mail, Bell, FileSearch
} from "lucide-react";

const TOOL_ICONS: Record<string, React.ReactNode> = {
  shell_exec:       <Terminal size={12} />,
  ssh_exec:         <Terminal size={12} />,
  execute_command:  <Terminal size={12} />,
  run_script:       <Play size={12} />,
  kill_process:     <XCircle size={12} />,
  file_write:       <FileText size={12} />,
  file_read:        <Eye size={12} />,
  file_edit:        <Edit3 size={12} />,
  file_delete:      <Trash2 size={12} />,
  file_copy:        <Copy size={12} />,
  file_move:        <Move size={12} />,
  file_search:      <FileSearch size={12} />,
  file_upload:      <Upload size={12} />,
  file_download:    <Download size={12} />,
  file_archive:     <Archive size={12} />,
  grep:             <FileSearch size={12} />,
  browser_navigate: <Globe size={12} />,
  browser_click:    <MousePointer size={12} />,
  browser_input:    <Type size={12} />,
  browser_scroll:   <ScrollText size={12} />,
  browser_view:     <Eye size={12} />,
  browser_close:    <XCircle size={12} />,
  browser_screenshot: <Image size={12} />,
  search_web:       <Search size={12} />,
  search:           <Search size={12} />,
  search_design_inspiration: <Palette size={12} />,
  pexels_search:    <Image size={12} />,
  message:          <MessageSquare size={12} />,
  send_email:       <Mail size={12} />,
  send_notification: <Bell size={12} />,
  image_generate:   <Image size={12} />,
  design_judge:     <Palette size={12} />,
  plan:             <FileText size={12} />,
  get_template:     <FileText size={12} />,
  schedule:         <Clock size={12} />,
  database_query:   <Database size={12} />,
  server_deploy:    <Server size={12} />,
  server_restart:   <RefreshCw size={12} />,
  git_commit:       <GitBranch size={12} />,
  git_push:         <Upload size={12} />,
  git_pull:         <Download size={12} />,
  npm_install:      <Package size={12} />,
  pip_install:      <Package size={12} />,
  SSH:              <Terminal size={12} />,
  Terminal:         <Terminal size={12} />,
  Browser:          <Globe size={12} />,
  Search:           <Search size={12} />,
};

function StatusIcon({ status }: { status: string }) {
  if (status === "running") return <Loader2 size={11} className="animate-spin text-blue-500 shrink-0" />;
  if (status === "success") return <CheckCircle2 size={11} className="text-green-500 shrink-0" />;
  if (status === "failed")  return <XCircle size={11} className="text-red-500 shrink-0" />;
  if (status === "warning" || status === "partial") return <AlertTriangle size={11} className="text-amber-500 shrink-0" />;
  if (status === "skipped") return <SkipForward size={11} className="text-gray-400 shrink-0" />;
  return <Clock size={11} className="text-gray-400 shrink-0" />;
}

interface StepChipProps {
  step: Step;
  active?: boolean;
  onClick: (step: Step) => void;
}

export function StepChip({ step, active, onClick }: StepChipProps) {
  const toolIcon = TOOL_ICONS[step.tool] ?? <Terminal size={12} />;
  const displayTitle = step.title || step.tool || "Шаг";

  return (
    <button
      onClick={() => onClick(step)}
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium transition-all cursor-pointer",
        "bg-[#F0EFED] hover:bg-[#E5E4E0]",
        "text-gray-600",
        "border border-transparent",
        active && "ring-1 ring-blue-400 bg-blue-50",
        step.status === "running" && "bg-blue-50 text-blue-700"
      )}
    >
      <span className="text-gray-400 shrink-0 flex items-center">
        {toolIcon}
      </span>
      <span className="truncate max-w-[180px]">{displayTitle}</span>
      <StatusIcon status={step.status} />
    </button>
  );
}
