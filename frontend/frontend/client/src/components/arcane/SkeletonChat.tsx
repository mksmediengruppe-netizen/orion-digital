// Design: "Warm Intelligence"
// Skeleton loading state for chat messages when switching between chats

import { cn } from "@/lib/utils";
import { motion } from "framer-motion";

function SkeletonLine({ width = "full", className }: { width?: string; className?: string }) {
  return (
    <div className={cn(
      "h-3 rounded-full bg-gray-200 animate-pulse",
      width === "full" ? "w-full" :
      width === "3/4" ? "w-3/4" :
      width === "2/3" ? "w-2/3" :
      width === "1/2" ? "w-1/2" :
      width === "1/3" ? "w-1/3" : width,
      className
    )} />
  );
}

function SkeletonUserMessage() {
  return (
    <div className="flex gap-3 justify-end">
      <div className="max-w-[60%] space-y-2">
        <div className="bg-gray-200 animate-pulse rounded-2xl rounded-tr-sm px-4 py-3 space-y-2">
          <SkeletonLine width="full" />
          <SkeletonLine width="3/4" />
        </div>
      </div>
      <div className="w-7 h-7 rounded-full bg-gray-200 animate-pulse shrink-0 mt-1" />
    </div>
  );
}

function SkeletonAgentMessage({ lines = 3, hasSteps = false }: { lines?: number; hasSteps?: boolean }) {
  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 rounded-full bg-gray-200 animate-pulse shrink-0 mt-1" />
      <div className="flex-1 min-w-0 space-y-2">
        <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 space-y-2.5">
          {Array.from({ length: lines }).map((_, i) => (
            <SkeletonLine
              key={i}
              width={i === lines - 1 ? "2/3" : i % 3 === 0 ? "3/4" : "full"}
            />
          ))}
        </div>
        {hasSteps && (
          <div className="flex gap-1.5 flex-wrap">
            {[60, 80, 70, 90].map((w, i) => (
              <div
                key={i}
                className="h-6 rounded-full bg-gray-200 animate-pulse"
                style={{ width: `${w}px` }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function SkeletonChat() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="px-4 py-6 space-y-5"
    >
      <SkeletonUserMessage />
      <SkeletonAgentMessage lines={4} hasSteps />
      <SkeletonUserMessage />
      <SkeletonAgentMessage lines={3} hasSteps={false} />
      <SkeletonAgentMessage lines={5} hasSteps />
    </motion.div>
  );
}
