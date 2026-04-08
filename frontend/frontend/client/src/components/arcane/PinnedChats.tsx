// Design: "Warm Intelligence"
// Pinned chats section for sidebar — pin important chats to the top

import { cn } from "@/lib/utils";
import { Pin, X, AlertTriangle } from "lucide-react";
import type { Chat } from "@/lib/mockData";

interface PinnedChatsProps {
  chats: Chat[];
  pinnedIds: Set<string>;
  activeChat: string;
  onChatSelect: (id: string) => void;
  onUnpin: (id: string) => void;
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

export function PinnedChats({ chats, pinnedIds, activeChat, onChatSelect, onUnpin }: PinnedChatsProps) {
  const pinned = chats.filter(c => pinnedIds.has(c.id));
  if (pinned.length === 0) return null;

  return (
    <div className="px-2 mb-2">
      <div className="flex items-center gap-1 px-1 py-1 mb-0.5">
        <Pin size={10} className="text-gray-400" />
        <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Закреплённые</span>
      </div>
      <div className="space-y-0.5">
        {pinned.map(chat => {
          const isNeedsReview = chat.status === "needs_review";
          return (
            <div
              key={chat.id}
              className={cn(
                "group flex items-center gap-1.5 px-2 py-1.5 rounded-md transition-colors cursor-pointer",
                activeChat === chat.id ? "bg-white shadow-sm" : "hover:bg-white/70"
              )}
              onClick={() => onChatSelect(chat.id)}
            >
              {isNeedsReview ? (
                <AlertTriangle size={10} className="text-yellow-500 shrink-0" />
              ) : (
                <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", STATUS_DOT[chat.status] ?? "bg-gray-300")} />
              )}
              <span className={cn(
                "flex-1 text-xs truncate",
                isNeedsReview ? "text-yellow-800 font-medium" : "text-gray-700"
              )}>
                {chat.title}
              </span>
              <button
                onClick={e => { e.stopPropagation(); onUnpin(chat.id); }}
                className="p-0.5 rounded text-gray-300 hover:text-gray-500 transition-colors opacity-0 group-hover:opacity-100"
                title="Открепить"
              >
                <X size={10} />
              </button>
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 border-b border-[#E8E6E1]" />
    </div>
  );
}
