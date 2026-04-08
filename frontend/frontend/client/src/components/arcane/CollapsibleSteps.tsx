// Manus-style CollapsibleSteps — flex-wrap pill layout
// Each step is a compact inline pill, not a full-width row
import { useState } from "react";
import { StepChip } from "./StepChip";
import type { Step } from "@/lib/mockData";
import { ChevronDown, ChevronRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface CollapsibleStepsProps {
  steps: Step[];
  activeStep?: string;
  onStepClick: (step: Step) => void;
}

export function CollapsibleSteps({ steps, activeStep, onStepClick }: CollapsibleStepsProps) {
  const [collapsed, setCollapsed] = useState(steps.length > 10);
  const visibleSteps = collapsed ? steps.slice(0, 8) : steps;
  const hiddenCount = steps.length - 8;

  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-1.5">
        <AnimatePresence initial={false}>
          {visibleSteps.map((step, i) => (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              transition={{ duration: 0.12, delay: i * 0.015 }}
              className="w-fit" style={{ display: "inline-flex" }}
            >
              <StepChip step={step} active={activeStep === step.id} onClick={onStepClick} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      {steps.length > 10 && (
        <button
          onClick={() => setCollapsed(v => !v)}
          className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600 transition-colors mt-1.5"
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
