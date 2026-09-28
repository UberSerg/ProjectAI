import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReleaseHistoryPanel } from "./ReleaseHistoryPanel";
import { makeTestRelease } from "./releaseHistory";

const older = makeTestRelease({
  version: "1.0.0",
  displayVersion: "Kraken V1.0",
  date: "2026-09-27",
  title: "First Release",
  summary: "Historical V1.0 summary snapshot",
  highlights: ["V1 highlight"],
  whatsNew: ["V1.0 feature — why it mattered then"],
  technicalNotes: ["V1 technical only"],
});

const newer = makeTestRelease({
  version: "9.1.0",
  displayVersion: "Kraken V9.1",
  date: "2026-12-01",
  title: "Fixture Newer",
  summary: "Current fixture summary — must not appear under V1.0",
  highlights: ["V9 highlight"],
  whatsNew: ["V9.1 feature — current only"],
  technicalNotes: ["V9 technical"],
});

describe("ReleaseHistoryPanel", () => {
  it("renders V1.0 date and expands its own historical notes", () => {
    render(
      <ReleaseHistoryPanel
        releases={[newer, older]}
        currentVersion="9.1.0"
        showTechnicalNotes
        initiallyExpandedVersion="9.1.0"
      />,
    );

    expect(screen.getByTestId("history-date-1.0.0")).toHaveTextContent("27.09.2026");

    fireEvent.click(screen.getByTestId("history-toggle-1.0.0"));
    expect(screen.getByTestId("history-details-1.0.0")).toBeInTheDocument();
    expect(screen.getByTestId("history-summary-1.0.0")).toHaveTextContent(
      "Historical V1.0 summary snapshot",
    );
    expect(screen.getByTestId("history-whats-new-1.0.0")).toHaveTextContent(
      "V1.0 feature — why it mattered then",
    );
    expect(screen.getByTestId("history-whats-new-1.0.0")).not.toHaveTextContent(
      "V9.1 feature — current only",
    );
    expect(screen.getByTestId("history-technical-1.0.0")).toHaveTextContent("V1 technical only");
    expect(screen.getByTestId("history-technical-1.0.0")).not.toHaveTextContent("V9 technical");
  });

  it("USER path can hide technical notes without losing human summary", () => {
    render(
      <ReleaseHistoryPanel
        releases={[older]}
        currentVersion="1.0.0"
        showTechnicalNotes={false}
        initiallyExpandedVersion="1.0.0"
      />,
    );
    expect(screen.getByTestId("history-summary-1.0.0")).toHaveTextContent(
      "Historical V1.0 summary snapshot",
    );
    expect(screen.queryByTestId("history-technical-1.0.0")).not.toBeInTheDocument();
  });
});
