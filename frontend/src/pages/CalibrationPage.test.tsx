import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HelpProvider } from "../help";
import { CalibrationPage } from "./CalibrationPage";

vi.mock("../api/investment", () => ({
  getCalibrationReport: vi.fn(async () => ({
    generated_at: "2026-09-05T00:00:00Z",
    pipeline: "Prediction → Calibration → Confidence → Allocation",
    candidate_v0: {
      id: "prediction_ml_candidate/v0",
      title: "Модель прогнозирования доходности",
      semantic: "EXPECTED_RETURN",
      calibration: {
        sample_count: 0,
        pending_count: 0,
        coverage: null,
        bias: null,
        mae: null,
        direction_accuracy: null,
        calibration_status: "INSUFFICIENT_SAMPLE",
        uncertainty_note: "нет пар",
        bias_sign: "none",
        buckets: [],
      },
      confidence: {
        confidence_level: "UNKNOWN",
        reason_ru: "Недостаточно зрелых прогнозов",
        sample_size: 0,
        calibration_status: "INSUFFICIENT_SAMPLE",
        reason_codes: ["insufficient_sample"],
      },
    },
    candidate_v1: {
      id: "prediction_ml_candidate/v1_ranker",
      title: "Модель ранжирования",
      semantic: "RANKING_SCORE",
      calibration: {
        sample_count: 0,
        pending_count: 0,
        coverage: null,
        mean_spearman_rank_ic: null,
        mean_top20_realized: null,
        mean_bottom20_realized: null,
        mean_top_minus_bottom: null,
        calibration_status: "INSUFFICIENT_SAMPLE",
        uncertainty_note: "нет ranking",
        rank_bucket_realized: [],
      },
      confidence: {
        confidence_level: "UNKNOWN",
        reason_ru: "UNKNOWN ranking",
        sample_size: 0,
        calibration_status: "INSUFFICIENT_SAMPLE",
      },
    },
    chart_data: { v0_buckets: [] },
    note: "no winner",
  })),
}));

describe("CalibrationPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders prediction quality page", async () => {
    render(
      <MemoryRouter>
        <HelpProvider>
          <CalibrationPage />
        </HelpProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Качество прогнозов Kraken")).toBeInTheDocument();
    expect(screen.getByText(/Модель прогнозирования доходности/)).toBeInTheDocument();
    expect(screen.getByText(/Модель ранжирования/)).toBeInTheDocument();
  });
});
