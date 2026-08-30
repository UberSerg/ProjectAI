import { useEffect, useRef } from "react";

/** Poll while `active` is true; pauses when the tab is hidden. */
export function usePolling(callback: () => void | Promise<void>, intervalMs: number, active: boolean) {
  const saved = useRef(callback);
  saved.current = callback;

  useEffect(() => {
    if (!active || intervalMs <= 0) return;
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      if (cancelled || document.visibilityState === "hidden") return;
      try {
        await saved.current();
      } catch {
        // swallow — caller handles errors inside callback
      }
    };

    timer = window.setInterval(() => {
      void tick();
    }, intervalMs);
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [active, intervalMs]);
}

export function isWorkflowActive(status?: string | null): boolean {
  const s = (status ?? "").toUpperCase();
  return s === "RUNNING" || s === "PENDING" || s === "CREATED";
}
