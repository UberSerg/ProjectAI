/** Typed help registry contracts for Control Center metrics and pages. */

export type HelpKind = "metric" | "term" | "page";

export interface HelpEntry {
  id: string;
  kind: HelpKind;
  title: string;
  /** Short text for tooltip / first glance. */
  summary: string;
  /** Longer explanation for the shared drawer. */
  details: string;
  /** How to read the value in ProjectAI. */
  interpretation?: string;
  /** Explicit non-goals / caveats. */
  limitations?: string[];
  relatedIds?: string[];
}

export interface PageHelpContent {
  id: string;
  title: string;
  about: string;
  understand: string[];
  metrics: string[];
  interpret: string[];
  limitations: string[];
}
