import { describe, expect, it } from "vitest";

import { contextFromShadowOrder, contextFromSimulatorFill } from "./adapters";
import { assertSafeWording, buildDecisionExplanation } from "./buildExplanation";
import { SUPPORTED_REASON_CODES, normalizeReasonCode } from "./registry";

describe("decision explanation registry", () => {
  it("covers required reason codes", () => {
    for (const code of [
      "ENTER_TOP20",
      "HOLD_WITHIN_EXIT_BAND",
      "EXIT_BELOW_TOP35",
      "REBALANCE_WEIGHT_DELTA",
      "BELOW_MIN_WEIGHT_DELTA",
      "DD_GUARD_REDUCE",
      "DD_GUARD_RECOVER",
      "RANK_LONG_ONLY_V0",
    ]) {
      expect(SUPPORTED_REASON_CODES).toContain(code);
    }
  });

  it("normalizes cash_scaled suffix", () => {
    expect(normalizeReasonCode("ENTER_TOP20|cash_scaled")).toBe("ENTER_TOP20");
  });
});

describe("AFLT ENTER_TOP20 acceptance facts", () => {
  it("renders short/detailed without inventing eligible count", () => {
    const fill = {
      execution_date: "2017-04-18",
      decision_date: "2017-04-17",
      instrument_id: 69,
      ticker: "AFLT",
      side: "BUY",
      quantity: 1,
      raw_open: 100,
      fill_price: 100,
      predicted_return_20d: 0.0585161185822529,
      rank: 5,
      target_weight: 0.125,
      prediction_date: "2017-04-17",
      policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
      reason: "ENTER_TOP20",
      display_name: "Aeroflot",
    };
    const expl = buildDecisionExplanation(contextFromSimulatorFill(fill));
    expect(expl.summary).toMatch(/Aeroflot|AFLT/);
    expect(expl.summary).toMatch(/\+5,85%/);
    expect(expl.summary).toMatch(/5-е место|5 из/);
    expect(expl.summary).toMatch(/12,50%/);
    expect(expl.summary).not.toMatch(/из 40/); // eligible not persisted → do not invent
    expect(expl.detailed).toMatch(/Next Open/);
    expect(expl.detailed).toMatch(/18\.04\.2017/);
    expect(expl.technical.some((f) => f.label === "Reason code" && f.value === "ENTER_TOP20")).toBe(
      true,
    );
    assertSafeWording(expl.summary);
    assertSafeWording(expl.detailed);
  });
});

describe("Shadow MGNT pending", () => {
  it("says selected for buy and waiting, not purchased", () => {
    const expl = buildDecisionExplanation(
      contextFromShadowOrder({
        ticker: "MGNT",
        side: "BUY",
        reason: "ENTER_TOP20",
        predicted_return_20d: 0.18999484146846618,
        rank: 1,
        eligible_count: 43,
        target_weight: 0.1111111111111111,
        status: "PENDING",
        min_execution_date: "2026-09-05",
        decision_at: "2026-09-04T14:15:29.275066+00:00",
        display_name: "Magnit",
        metadata: {
          kind: "FORWARD_SHADOW",
          policy: "RANK_HYSTERESIS_LONG_ONLY_V1",
          risk_mode: "normal",
          signal_as_of: "2026-09-02",
          forward_batch_id: 1,
          signal_generated_at: "2026-09-04T13:40:38.343892+00:00",
        },
      }),
    );
    expect(expl.summary).toMatch(/выбран для покупки|ордер/i);
    expect(expl.summary).toMatch(/1 из 43/);
    expect(expl.summary).toMatch(/\+19,00%/);
    expect(expl.summary).toMatch(/ожидает|не исполнен/i);
    expect(expl.summary).not.toMatch(/куплен|купили/i);
    expect(expl.detailed).toMatch(/ожидает первого допустимого будущего/i);
    expect(expl.technical.some((f) => f.label === "Order status" && f.value === "PENDING")).toBe(
      true,
    );
    expect(expl.timeline.some((t) => t.label.includes("ожидает"))).toBe(true);
  });
});

describe("policy reason variants", () => {
  it("explains HOLD_WITHIN_EXIT_BAND", () => {
    const expl = buildDecisionExplanation({
      reasonCode: "HOLD_WITHIN_EXIT_BAND",
      ticker: "SBER",
      rank: 12,
      eligibleCount: 43,
      entryQuantile: 0.2,
      exitQuantile: 0.35,
      policyName: "RANK_HYSTERESIS_LONG_ONLY_V1",
    });
    expect(expl.summary).toMatch(/сохранена/i);
    expect(expl.detailed).toMatch(/удержания/i);
    expect(expl.detailed).not.toMatch(/гарантированно/i);
  });

  it("explains EXIT_BELOW_TOP35", () => {
    const expl = buildDecisionExplanation({
      reasonCode: "EXIT_BELOW_TOP35",
      ticker: "GAZP",
      rank: 20,
      eligibleCount: 43,
      exitQuantile: 0.35,
      side: "SELL",
      executionDate: "2024-02-01",
      decisionDate: "2024-01-31",
      orderStatus: "FILLED",
    });
    expect(expl.summary).toMatch(/закрыта/i);
    expect(expl.detailed).toMatch(/20 из 43/);
    expect(expl.detailed).not.toMatch(/плохой/i);
  });

  it("explains REBALANCE_WEIGHT_DELTA with weights", () => {
    const expl = buildDecisionExplanation({
      reasonCode: "REBALANCE_WEIGHT_DELTA",
      ticker: "LKOH",
      currentWeight: 0.101,
      targetWeight: 0.125,
      minTradeWeightDelta: 0.02,
      orderStatus: "FILLED",
      executionDate: "2024-03-01",
      decisionDate: "2024-02-28",
    });
    expect(expl.summary).toMatch(/скорректирована/i);
    expect(expl.detailed).toMatch(/10,10%/);
    expect(expl.detailed).toMatch(/12,50%/);
    expect(expl.detailed).toMatch(/2,0 п\.п\./);
  });

  it("explains BELOW_MIN_WEIGHT_DELTA as no trade", () => {
    const expl = buildDecisionExplanation({
      reasonCode: "BELOW_MIN_WEIGHT_DELTA",
      ticker: "ROSN",
      currentWeight: 0.11,
      targetWeight: 0.125,
      minTradeWeightDelta: 0.02,
      actionKind: "NO_TRADE",
    });
    expect(expl.summary).toMatch(/не выполнялась/i);
    expect(expl.detailed).toMatch(/2,0 п\.п\./);
  });

  it("explains DD reduce/recover", () => {
    const reduce = buildDecisionExplanation({
      reasonCode: "DD_GUARD_REDUCE",
      drawdown: -0.203,
      previousExposureCap: 1,
      newExposureCap: 0.5,
      riskPolicyName: "DRAWDOWN_GUARD_V1",
    });
    expect(reduce.summary).toMatch(/снижен/i);
    expect(reduce.detailed).toMatch(/-20,3%/);
    expect(reduce.detailed).toMatch(/50%/);

    const recover = buildDecisionExplanation({
      reasonCode: "DD_GUARD_RECOVER",
      drawdown: -0.096,
      previousExposureCap: 0.5,
      newExposureCap: 1,
    });
    expect(recover.summary).toMatch(/восстановить/i);
    expect(recover.detailed).toMatch(/-9,6%/);
  });

  it("falls back for unknown reason and keeps raw code in technical", () => {
    const expl = buildDecisionExplanation({
      reasonCode: "SOME_NEW_CODE",
      ticker: "X",
      predictedReturn20d: 0.01,
    });
    expect(expl.usedFallback).toBe(true);
    expect(expl.summary).toMatch(/портфельной политикой/i);
    expect(expl.technical.some((f) => f.value.includes("SOME_NEW_CODE"))).toBe(true);
  });

  it("distinguishes model vs policy wording", () => {
    const expl = buildDecisionExplanation({
      reasonCode: "ENTER_TOP20",
      ticker: "MGNT",
      rank: 1,
      eligibleCount: 43,
      predictedReturn20d: 0.19,
      targetWeight: 0.1111,
      policyName: "RANK_HYSTERESIS_LONG_ONLY_V1",
      orderStatus: "FILLED",
      predictionDate: "2026-09-02",
      executionDate: "2026-09-05",
      decisionDate: "2026-09-04",
    });
    expect(expl.detailed).toMatch(/Решение о позиции принимает политика/i);
    expect(expl.detailed).not.toMatch(/модель решила купить/i);
  });
});

describe("RANKING_SCORE explanation", () => {
  it("does not format ranking score as predicted return %", () => {
    const fill = {
      execution_date: "2017-04-18",
      decision_date: "2017-04-17",
      instrument_id: 1,
      ticker: "LKOH",
      side: "BUY",
      quantity: 1,
      raw_open: 100,
      fill_price: 100,
      predicted_return_20d: 1.37,
      rank: 4,
      target_weight: 0.125,
      prediction_date: "2017-04-17",
      policy_name: "RANK_HYSTERESIS_LONG_ONLY_V1",
      reason: "ENTER_TOP20",
      display_name: "Lukoil",
      metadata: {
        prediction_semantic: "RANKING_SCORE",
        prediction_score: 1.37,
        prediction_candidate: "prediction_ml_candidate/v1_ranker",
        eligible_n: 41,
      },
    };
    const expl = buildDecisionExplanation(
      contextFromSimulatorFill(fill, {
        predictionCandidate: "prediction_ml_candidate/v1_ranker",
      }),
    );
    expect(expl.summary).not.toMatch(/\+1[,.]37/);
    expect(expl.summary).not.toMatch(/прогноз/i);
    expect(expl.detailed).toMatch(/рейтинговый балл|порядка/i);
    expect(expl.detailed).not.toMatch(/ожидаемого изменения цены/i);
    expect(expl.technical.some((f) => f.label === "Ranking score" && f.value === "1.37")).toBe(
      true,
    );
    expect(expl.technical.some((f) => f.label === "Prediction semantic")).toBe(true);
    expect(expl.technical.some((f) => f.label === "Predicted return 20d")).toBe(false);
    expect(
      expl.technical.some(
        (f) => f.label === "Prediction candidate (human)" && f.value === "Модель ранжирования V1",
      ),
    ).toBe(true);
    assertSafeWording(expl.summary);
    assertSafeWording(expl.detailed);
  });
});
