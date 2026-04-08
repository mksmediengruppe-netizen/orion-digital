// NotificationCenter — Demo email notification UI for ARCANE
// Design: Notion-style side panel with bell icon, unread badge, notification log, email preview modal
// No real email sending — simulates the UX for developer handoff

import { useState, useEffect, useRef } from "react";
import { Bell, X, Mail, ExternalLink, Check, AlertTriangle, Clock, ChevronRight, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";

export interface AppNotification {
  id: string;
  type: "budget_exhausted" | "budget_warning" | "task_failed" | "needs_review";
  title: string;
  body: string;
  userName: string;
  userEmail: string;
  adminEmail: string;
  amount?: number;
  limit?: number;
  taskName?: string;
  timestamp: Date;
  read: boolean;
  emailSent: boolean; // simulated
}

interface NotificationCenterProps {
  notifications: AppNotification[];
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  onDismiss: (id: string) => void;
  onClearAll: () => void;
}

// Renders a full HTML email preview (simulated)
function EmailPreviewModal({
  notification,
  onClose,
}: {
  notification: AppNotification;
  onClose: () => void;
}) {
  const ts = notification.timestamp;
  const dateStr = ts.toLocaleDateString("ru-RU", { day: "2-digit", month: "long", year: "numeric" });
  const timeStr = ts.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });

  const subject =
    notification.type === "budget_exhausted"
      ? `⚠️ Бюджет исчерпан: ${notification.userName}`
      : notification.type === "budget_warning"
      ? `🔔 Предупреждение о бюджете: ${notification.userName}`
      : `Уведомление ARCANE: ${notification.title}`;

  const emailHtml = `
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">
      <!-- Header -->
      <div style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 28px 32px;">
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 4px;">
          <div style="width: 28px; height: 28px; background: rgba(255,255,255,0.2); border-radius: 8px; display: flex; align-items: center; justify-content: center;">
            <span style="color: white; font-size: 14px; font-weight: 700;">O</span>
          </div>
          <span style="color: rgba(255,255,255,0.9); font-size: 13px; font-weight: 600; letter-spacing: 0.05em;">ARCANE AI</span>
        </div>
        <h1 style="color: white; font-size: 20px; font-weight: 700; margin: 12px 0 4px;">${
          notification.type === "budget_exhausted" ? "Бюджет пользователя исчерпан" : notification.title
        }</h1>
        <p style="color: rgba(255,255,255,0.75); font-size: 13px; margin: 0;">${dateStr} в ${timeStr}</p>
      </div>

      <!-- Body -->
      <div style="padding: 28px 32px;">
        <p style="color: #374151; font-size: 14px; line-height: 1.6; margin: 0 0 20px;">
          Здравствуйте, администратор!
        </p>
        ${
          notification.type === "budget_exhausted"
            ? `<div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
              <span style="font-size: 16px;">⚠️</span>
              <span style="color: #dc2626; font-weight: 600; font-size: 14px;">Бюджет исчерпан</span>
            </div>
            <p style="color: #7f1d1d; font-size: 13px; margin: 0; line-height: 1.5;">
              Пользователь <strong>${notification.userName}</strong> (${notification.userEmail}) израсходовал весь выделенный бюджет.
              Все активные задачи автоматически остановлены. Новые задачи заблокированы до пополнения.
            </p>
          </div>`
            : `<div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;">
            <p style="color: #92400e; font-size: 13px; margin: 0;">${notification.body}</p>
          </div>`
        }

        <!-- Stats -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 24px;">
          <div style="background: #f9fafb; border-radius: 8px; padding: 14px 16px;">
            <div style="color: #9ca3af; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">Потрачено</div>
            <div style="color: #111827; font-size: 18px; font-weight: 700; font-family: monospace;">$${notification.amount?.toFixed(2) ?? "—"}</div>
          </div>
          <div style="background: #f9fafb; border-radius: 8px; padding: 14px 16px;">
            <div style="color: #9ca3af; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">Лимит</div>
            <div style="color: #111827; font-size: 18px; font-weight: 700; font-family: monospace;">$${notification.limit?.toFixed(2) ?? "—"}</div>
          </div>
        </div>

        <!-- Progress bar -->
        <div style="margin-bottom: 24px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <span style="color: #6b7280; font-size: 12px;">Использование бюджета</span>
            <span style="color: #dc2626; font-size: 12px; font-weight: 600;">100%</span>
          </div>
          <div style="height: 8px; background: #f3f4f6; border-radius: 4px; overflow: hidden;">
            <div style="height: 100%; width: 100%; background: linear-gradient(90deg, #ef4444, #dc2626); border-radius: 4px;"></div>
          </div>
        </div>

        <!-- CTA -->
        <div style="text-align: center; margin-bottom: 24px;">
          <a href="#" style="display: inline-block; background: #4f46e5; color: white; text-decoration: none; padding: 12px 28px; border-radius: 8px; font-size: 14px; font-weight: 600;">
            Открыть Админку → Пользователи
          </a>
        </div>

        <p style="color: #9ca3af; font-size: 12px; line-height: 1.5; margin: 0;">
          Это автоматическое уведомление от системы ARCANE AI.<br/>
          Для управления уведомлениями перейдите в Админку → Пользователи → Бюджет.
        </p>
      </div>

      <!-- Footer -->
      <div style="background: #f9fafb; padding: 16px 32px; border-top: 1px solid #f3f4f6;">
        <p style="color: #9ca3af; font-size: 11px; margin: 0; text-align: center;">
          ARCANE AI Interface · Кому: ${notification.adminEmail} · ${dateStr}
        </p>
      </div>
    </div>
  `;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 10 }}
        className="bg-white rounded-2xl shadow-2xl w-full max-w-[600px] max-h-[90vh] flex flex-col overflow-hidden"
      >
        {/* Modal header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-indigo-50 flex items-center justify-center">
              <Mail size={13} className="text-indigo-600" />
            </div>
            <div>
              <div className="text-sm font-semibold text-gray-900">Предпросмотр письма</div>
              <div className="text-[11px] text-gray-400">Кому: {notification.adminEmail}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-2.5 py-1 bg-green-50 rounded-full">
              <Check size={10} className="text-green-600" />
              <span className="text-[10px] font-medium text-green-700">Отправлено (демо)</span>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 transition-colors">
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Email meta */}
        <div className="px-5 py-3 bg-gray-50 border-b border-gray-100 space-y-1">
          <div className="flex gap-2 text-xs">
            <span className="text-gray-400 w-14 shrink-0">Тема:</span>
            <span className="text-gray-700 font-medium">{subject}</span>
          </div>
          <div className="flex gap-2 text-xs">
            <span className="text-gray-400 w-14 shrink-0">От:</span>
            <span className="text-gray-600">noreply@arcane.ai</span>
          </div>
          <div className="flex gap-2 text-xs">
            <span className="text-gray-400 w-14 shrink-0">Кому:</span>
            <span className="text-gray-600">{notification.adminEmail}</span>
          </div>
        </div>

        {/* Email body preview */}
        <div className="flex-1 overflow-y-auto p-5 bg-[#f5f5f5]">
          <div
            className="bg-white rounded-xl overflow-hidden"
            dangerouslySetInnerHTML={{ __html: emailHtml }}
          />
        </div>
      </motion.div>
    </div>
  );
}

const TYPE_CONFIG: Record<AppNotification["type"], { icon: React.ReactNode; color: string; bg: string; label: string }> = {
  budget_exhausted: {
    icon: <AlertTriangle size={13} />,
    color: "text-red-600",
    bg: "bg-red-50",
    label: "Бюджет исчерпан",
  },
  budget_warning: {
    icon: <Bell size={13} />,
    color: "text-amber-600",
    bg: "bg-amber-50",
    label: "Предупреждение",
  },
  task_failed: {
    icon: <X size={13} />,
    color: "text-red-500",
    bg: "bg-red-50",
    label: "Ошибка задачи",
  },
  needs_review: {
    icon: <Clock size={13} />,
    color: "text-yellow-600",
    bg: "bg-yellow-50",
    label: "На проверке",
  },
};

export function NotificationCenter({
  notifications,
  onMarkRead,
  onMarkAllRead,
  onDismiss,
  onClearAll,
}: NotificationCenterProps) {
  const [open, setOpen] = useState(false);
  const [previewNotif, setPreviewNotif] = useState<AppNotification | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const unread = notifications.filter(n => !n.read).length;

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  const formatTime = (d: Date) => {
    const diff = Date.now() - d.getTime();
    if (diff < 60000) return "только что";
    if (diff < 3600000) return `${Math.floor(diff / 60000)} мин назад`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} ч назад`;
    return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
  };

  return (
    <div className="relative" ref={panelRef}>
      {/* Bell button */}
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "relative p-2 rounded-lg transition-colors",
          open ? "bg-indigo-50 text-indigo-600" : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        )}
        title="Уведомления"
      >
        <Bell size={16} />
        {unread > 0 && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center"
          >
            {unread > 9 ? "9+" : unread}
          </motion.span>
        )}
      </button>

      {/* Panel */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.97 }}
            transition={{ duration: 0.15 }}
            className="absolute bottom-full mb-2 left-0 w-[340px] bg-white rounded-2xl shadow-2xl border border-gray-100 overflow-hidden z-50"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <Bell size={14} className="text-gray-600" />
                <span className="text-sm font-semibold text-gray-800">Уведомления</span>
                {unread > 0 && (
                  <span className="px-1.5 py-0.5 bg-red-100 text-red-600 text-[10px] font-bold rounded-full">
                    {unread}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                {unread > 0 && (
                  <button
                    onClick={onMarkAllRead}
                    className="text-[11px] text-indigo-600 hover:text-indigo-800 px-2 py-1 rounded hover:bg-indigo-50 transition-colors"
                  >
                    Прочитать все
                  </button>
                )}
                {notifications.length > 0 && (
                  <button
                    onClick={onClearAll}
                    className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                    title="Очистить все"
                  >
                    <Trash2 size={12} />
                  </button>
                )}
              </div>
            </div>

            {/* List */}
            <div className="max-h-[360px] overflow-y-auto">
              {notifications.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-gray-400">
                  <Bell size={24} className="mb-2 opacity-30" />
                  <span className="text-xs">Нет уведомлений</span>
                </div>
              ) : (
                <div className="divide-y divide-gray-50">
                  {notifications.map(n => {
                    const cfg = TYPE_CONFIG[n.type];
                    return (
                      <div
                        key={n.id}
                        className={cn(
                          "flex gap-3 px-4 py-3 hover:bg-gray-50 transition-colors cursor-pointer group",
                          !n.read && "bg-indigo-50/40"
                        )}
                        onClick={() => {
                          onMarkRead(n.id);
                          if (n.type === "budget_exhausted" || n.type === "budget_warning") {
                            setPreviewNotif(n);
                          }
                        }}
                      >
                        {/* Icon */}
                        <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5", cfg.bg, cfg.color)}>
                          {cfg.icon}
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-1">
                            <div className="text-xs font-semibold text-gray-800 leading-tight">{n.title}</div>
                            <div className="flex items-center gap-1 shrink-0">
                              {!n.read && <div className="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0" />}
                              <button
                                onClick={e => { e.stopPropagation(); onDismiss(n.id); }}
                                className="opacity-0 group-hover:opacity-100 p-0.5 text-gray-300 hover:text-gray-500 transition-all"
                              >
                                <X size={10} />
                              </button>
                            </div>
                          </div>
                          <div className="text-[11px] text-gray-500 mt-0.5 leading-relaxed line-clamp-2">{n.body}</div>
                          <div className="flex items-center gap-2 mt-1.5">
                            <span className="text-[10px] text-gray-400">{formatTime(n.timestamp)}</span>
                            {n.emailSent && (
                              <div className="flex items-center gap-1">
                                <Mail size={9} className="text-green-500" />
                                <span className="text-[10px] text-green-600">Email отправлен</span>
                              </div>
                            )}
                            {(n.type === "budget_exhausted" || n.type === "budget_warning") && (
                              <div className="flex items-center gap-0.5 text-[10px] text-indigo-500 hover:text-indigo-700">
                                <span>Просмотр письма</span>
                                <ChevronRight size={9} />
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer */}
            {notifications.length > 0 && (
              <div className="px-4 py-2.5 border-t border-gray-100 bg-gray-50">
                <p className="text-[10px] text-gray-400 text-center">
                  Демо-режим · Реальная отправка требует настройки SMTP
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Email preview modal */}
      <AnimatePresence>
        {previewNotif && (
          <EmailPreviewModal
            notification={previewNotif}
            onClose={() => setPreviewNotif(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
