/** Deterministic sample-maturity labels for prospective A/B (Russian UI). */

export type SampleMaturityCode =
  | "TOO_EARLY"
  | "VERY_FEW"
  | "PRELIMINARY"
  | "ACCUMULATING"
  | "SUBSTANTIAL";

export function sampleMaturityCode(matureDates: number): SampleMaturityCode {
  if (matureDates <= 0) return "TOO_EARLY";
  if (matureDates <= 4) return "VERY_FEW";
  if (matureDates <= 19) return "PRELIMINARY";
  if (matureDates <= 49) return "ACCUMULATING";
  return "SUBSTANTIAL";
}

export function sampleMaturityLabel(codeOrCount: SampleMaturityCode | number | string | null | undefined): string {
  let code: SampleMaturityCode;
  if (typeof codeOrCount === "number") {
    code = sampleMaturityCode(codeOrCount);
  } else if (typeof codeOrCount === "string") {
    const upper = codeOrCount.toUpperCase();
    if (
      upper === "TOO_EARLY" ||
      upper === "VERY_FEW" ||
      upper === "PRELIMINARY" ||
      upper === "ACCUMULATING" ||
      upper === "SUBSTANTIAL"
    ) {
      code = upper;
    } else {
      const n = Number(codeOrCount);
      code = Number.isFinite(n) ? sampleMaturityCode(n) : "TOO_EARLY";
    }
  } else {
    code = "TOO_EARLY";
  }

  switch (code) {
    case "TOO_EARLY":
      return "Слишком рано для оценки";
    case "VERY_FEW":
      return "Очень мало наблюдений";
    case "PRELIMINARY":
      return "Предварительные данные";
    case "ACCUMULATING":
      return "История начинает накапливаться";
    case "SUBSTANTIAL":
      return "Накоплена более содержательная выборка";
    default:
      return "Слишком рано для оценки";
  }
}
