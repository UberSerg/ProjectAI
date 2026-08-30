import { afterEach, describe, expect, it, vi } from "vitest";
import { isWorkflowActive, usePolling } from "./usePolling";
import { act, render } from "@testing-library/react";

function Probe({
  active,
  intervalMs,
  onTick,
}: {
  active: boolean;
  intervalMs: number;
  onTick: () => void;
}) {
  usePolling(onTick, intervalMs, active);
  return null;
}

describe("isWorkflowActive", () => {
  it("treats CREATED/PENDING/RUNNING as active", () => {
    expect(isWorkflowActive("CREATED")).toBe(true);
    expect(isWorkflowActive("PENDING")).toBe(true);
    expect(isWorkflowActive("RUNNING")).toBe(true);
    expect(isWorkflowActive("SUCCESS")).toBe(false);
    expect(isWorkflowActive("WARNING")).toBe(false);
    expect(isWorkflowActive("ERROR")).toBe(false);
  });
});

describe("usePolling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("ticks while active and stops when inactive", async () => {
    vi.useFakeTimers();
    const onTick = vi.fn();
    const { rerender } = render(<Probe active intervalMs={2000} onTick={onTick} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(onTick).toHaveBeenCalledTimes(1);

    rerender(<Probe active={false} intervalMs={2000} onTick={onTick} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(onTick).toHaveBeenCalledTimes(1);
  });
});
