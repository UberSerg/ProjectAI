import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  Accordion,
  DecisionActionChip,
  EmptyState,
  ErrorState,
  FreshnessBadge,
  InlineNotice,
  LoadingSkeleton,
  PageState,
  ProvenanceBadge,
  StatusBadge,
  resolveDecisionAction,
  resolveFreshnessTone,
  resolveProvenanceTone,
  resolveStatusTone,
  DataQualityNote,
} from "./Ui";

describe("Ui status / action / freshness resolvers", () => {
  it("maps operational statuses", () => {
    expect(resolveStatusTone("healthy")).toBe("success");
    expect(resolveStatusTone("stale")).toBe("warning");
    expect(resolveStatusTone("blocked")).toBe("blocked");
    expect(resolveStatusTone("research_only")).toBe("research");
    expect(resolveStatusTone("weird")).toBe("unknown");
  });

  it("maps decision actions", () => {
    expect(resolveDecisionAction("BUY")).toBe("buy");
    expect(resolveDecisionAction("consider_reduce")).toBe("sell");
    expect(resolveDecisionAction("REVIEW_HOLD")).toBe("hold");
    expect(resolveDecisionAction("rotate")).toBe("review");
  });

  it("maps freshness and provenance", () => {
    expect(resolveFreshnessTone("FRESH")).toBe("fresh");
    expect(resolveFreshnessTone("STALE")).toBe("stale");
    expect(resolveFreshnessTone("MIXED")).toBe("partial");
    expect(resolveFreshnessTone("SESSION_NOT_STARTED")).toBe("unavailable");
    expect(resolveProvenanceTone("LIVE")).toBe("live");
    expect(resolveProvenanceTone("COUNTERFACTUAL_REPLAY")).toBe("counterfactual");
  });
});

describe("Ui badges and chips", () => {
  it("renders StatusBadge tones", () => {
    render(<StatusBadge status="ok" />);
    const badge = screen.getByText("Работает");
    expect(badge.className).toMatch(/badge-success/);
  });

  it("renders DecisionActionChip", () => {
    render(<DecisionActionChip action="BUY" />);
    const chip = screen.getByText("BUY");
    expect(chip).toHaveAttribute("data-action", "buy");
    expect(chip.className).toContain("ds-action-buy");
  });

  it("renders FreshnessBadge and ProvenanceBadge", () => {
    render(
      <>
        <FreshnessBadge value="STALE" />
        <ProvenanceBadge value="COUNTERFACTUAL_REPLAY" />
      </>,
    );
    expect(screen.getByText("STALE")).toHaveAttribute("data-freshness", "stale");
    expect(screen.getByText("COUNTERFACTUAL")).toHaveAttribute("data-provenance", "counterfactual");
  });
});

describe("Ui state primitives", () => {
  it("renders EmptyState, ErrorState, InlineNotice, DataQualityNote", () => {
    render(
      <>
        <EmptyState title="Пусто" reason="Нет сделок" />
        <ErrorState title="Ошибка">Сеть недоступна</ErrorState>
        <InlineNotice tone="warning" title="Внимание">
          Частичные котировки
        </InlineNotice>
        <DataQualityNote title="Качество" tone="warning">
          STALE ≠ FULL
        </DataQualityNote>
      </>,
    );
    expect(screen.getByText("Пусто")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Ошибка");
    expect(screen.getByText("Внимание")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveAttribute("data-tone", "warning");
  });

  it("LoadingSkeleton reserves layout without inventing zeros", () => {
    render(<LoadingSkeleton label="Загрузка портфеля…" rows={2} />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Загрузка портфеля…")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("PageState routes loading/error/empty", () => {
    const { rerender } = render(<PageState kind="loading" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    rerender(<PageState kind="error" title="Сбой" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Сбой");
    rerender(<PageState kind="empty" title="Нет данных" />);
    expect(screen.getByText("Нет данных")).toBeInTheDocument();
  });

  it("Accordion expands details for Journal-style cards", () => {
    render(
      <Accordion title="День 2026-10-28" defaultOpen>
        <p>Детали решения</p>
      </Accordion>,
    );
    const details = screen.getByText("День 2026-10-28").closest("details");
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("Детали решения")).toBeInTheDocument();
  });
});
