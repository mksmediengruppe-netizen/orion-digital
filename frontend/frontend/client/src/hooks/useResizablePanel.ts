// useResizablePanel — drag-to-resize hook for the right panel
// Returns width, a ref for the drag handle, and isResizing state

import { useState, useRef, useCallback, useEffect } from "react";

interface UseResizablePanelOptions {
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
  side?: "left" | "right"; // which side the handle is on
}

export function useResizablePanel({
  defaultWidth,
  minWidth,
  maxWidth,
  side = "left",
}: UseResizablePanelOptions) {
  const [width, setWidth] = useState(defaultWidth);
  const [isResizing, setIsResizing] = useState(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(defaultWidth);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    startXRef.current = e.clientX;
    startWidthRef.current = width;
  }, [width]);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const delta = side === "left"
        ? startXRef.current - e.clientX  // dragging left handle: move left = wider
        : e.clientX - startXRef.current; // dragging right handle: move right = wider
      const newWidth = Math.min(maxWidth, Math.max(minWidth, startWidthRef.current + delta));
      setWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing, side, minWidth, maxWidth]);

  return { width, isResizing, handleMouseDown };
}
