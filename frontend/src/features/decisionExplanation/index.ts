export { buildDecisionExplanation, assertSafeWording } from "./buildExplanation";
export {
  contextFromSimulatorFill,
  contextFromSimulatorOrder,
  contextFromShadowOrder,
} from "./adapters";
export { DecisionExplanationPanel } from "./DecisionExplanationPanel";
export {
  DECISION_EXPLANATION_REGISTRY,
  SUPPORTED_REASON_CODES,
  normalizeReasonCode,
  getReasonDefinition,
} from "./registry";
export type {
  DecisionExplanation,
  DecisionExplanationContext,
  TechnicalField,
} from "./types";
