import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CatchUpStatusCard } from "./CatchUpStatusCard";

describe("CatchUpStatusCard market/shadow recovery", () => {
  it("renders separate market and shadow sections for OWNER recovery view", () => {
    render(
      <CatchUpStatusCard
        catchUp={{
          catch_up_status: "CATCH_UP_BLOCKED",
          latest_completed_market_session: "2026-09-10",
          backlog_session_count: 0,
          blocking_reason: "MISSING_MARKET_DATA",
          blocking_session: "2026-09-11",
          market_data: {
            latest_local_eod_session: "2026-09-10",
            latest_expected_completed_session: "2026-09-25",
            missing_market_sessions_count: 11,
            market_current: false,
            market_backfill_status: "MARKET_STALE",
          },
          shadow: {
            last_processed_session: "2026-09-10",
            replay_backlog: 0,
            catch_up_status: "CATCH_UP_BLOCKED",
          },
          portfolios: [
            {
              portfolio_id: 1,
              name: "SHADOW_HYSTERESIS_V1",
              last_processed_session: "2026-09-10",
              backlog_count: 0,
            },
          ],
        }}
      />,
    );

    expect(screen.getByTestId("catchup-market-section")).toBeInTheDocument();
    expect(screen.getByTestId("catchup-shadow-section")).toBeInTheDocument();
    expect(screen.getByTestId("market-local-eod")).toHaveTextContent("2026-09-10");
    expect(screen.getByTestId("market-expected-eod")).toHaveTextContent("2026-09-25");
    expect(screen.getByTestId("market-missing-count")).toHaveTextContent("11");
    expect(screen.getByTestId("market-current-flag")).toHaveTextContent("NO");
    expect(screen.getByTestId("shadow-catchup-backlog")).toHaveTextContent("0");
  });
});
