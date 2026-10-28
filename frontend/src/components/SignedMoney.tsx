import type { ReactNode } from "react";
import { formatRub } from "../utils/format";

export type SignedMoneyTone = "positive" | "negative" | "neutral" | "partial";

export interface SignedMoneyProps {
  value?: number | null;
  /** When true, value is incomplete portfolio P&L — never paint as full profit/loss. */
  partial?: boolean;
  className?: string;
  "data-testid"?: string;
  /** Show explicit + for gains (default true). */
  showPlus?: boolean;
}

export function signedMoneyTone(value?: number | null, partial = false): SignedMoneyTone {
  if (partial || value == null || Number.isNaN(value)) return partial && value != null ? "partial" : "neutral";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

export function formatSignedRub(value?: number | null, showPlus = true): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (value === 0) return formatRub(0);
  const body = formatRub(Math.abs(value));
  if (value > 0) return showPlus ? `+${body}` : body;
  return `−${body}`;
}

/** P&L-only money: green gain / red loss / neutral zero or unavailable. */
export function SignedMoney({
  value,
  partial = false,
  className,
  showPlus = true,
  "data-testid": testId,
}: SignedMoneyProps): ReactNode {
  const tone = signedMoneyTone(value, partial);
  const text =
    partial && value != null && !Number.isNaN(value)
      ? `${formatSignedRub(value, showPlus)} · частично`
      : formatSignedRub(value, showPlus);
  return (
    <span
      className={["signed-money", `signed-money-${tone}`, className].filter(Boolean).join(" ")}
      data-testid={testId}
      data-tone={tone}
    >
      {text}
    </span>
  );
}
