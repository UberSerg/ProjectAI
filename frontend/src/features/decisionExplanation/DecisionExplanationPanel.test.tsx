import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HelpProvider } from "../../help/HelpContext";
import { DecisionExplanationPanel } from "./DecisionExplanationPanel";

function renderPanel() {
  return render(
    <HelpProvider>
      <DecisionExplanationPanel
        context={{
          reasonCode: "ENTER_TOP20",
          ticker: "AFLT",
          displayName: "Aeroflot",
          side: "BUY",
          predictedReturn20d: 0.0585,
          rank: 5,
          targetWeight: 0.125,
          policyName: "RANK_HYSTERESIS_LONG_ONLY_V1",
          predictionDate: "2017-04-17",
          decisionDate: "2017-04-17",
          executionDate: "2017-04-18",
          orderStatus: "FILLED",
          executionRule: "NEXT_OPEN",
        }}
        onClose={() => undefined}
      />
    </HelpProvider>,
  );
}

describe("DecisionExplanationPanel", () => {
  it("shows summary and expands details / technical", () => {
    renderPanel();
    expect(screen.getByText("Почему была сделка?")).toBeInTheDocument();
    expect(screen.getByText(/Aeroflot|верхние 20%/)).toBeInTheDocument();
    expect(screen.getByText(/\+5,85%/)).toBeInTheDocument();

    const detailsBtn = screen.getByRole("button", { name: /Подробнее/i });
    expect(detailsBtn).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(detailsBtn);
    expect(detailsBtn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Next Open/i)).toBeInTheDocument();

    const techBtn = screen.getByRole("button", { name: /Технические детали/i });
    fireEvent.click(techBtn);
    expect(techBtn).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Reason code")).toBeInTheDocument();
    expect(screen.getByText("ENTER_TOP20")).toBeInTheDocument();
  });
});
