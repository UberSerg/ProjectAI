import { labels } from "../utils/labels";
import type { KrakenPresentationRole } from "../role/types";

export interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  soon?: boolean;
}

export interface NavGroupDef {
  title?: string;
  items: NavItem[];
}

const userNav: NavGroupDef[] = [
  {
    items: [
      { to: "/", label: labels.nav.overview, end: true },
      { to: "/portfolio/mine", label: "Портфель" },
      { to: "/investment-decision", label: "Решения" },
      { to: "/portfolio/mine?tab=analysis", label: "История" },
    ],
  },
];

const ownerNav: NavGroupDef[] = [
  { items: [{ to: "/", label: labels.nav.overview, end: true }] },
  {
    title: labels.nav.portfolioGroup,
    items: [
      { to: "/portfolio/mine", label: labels.nav.myPortfolio },
      { to: "/portfolio/candidate", label: labels.nav.portfolioCandidate },
      { to: "/investment-decision", label: labels.nav.investmentDecision },
      { to: "/portfolio-risk", label: labels.nav.portfolioRisk },
    ],
  },
  {
    title: labels.nav.marketGroup,
    items: [
      { to: "/market", label: labels.nav.quotes },
      { to: "/instruments", label: labels.nav.instruments },
      { to: "/fundamentals", label: labels.nav.companies },
      { to: "/bonds", label: labels.nav.bonds },
    ],
  },
  {
    title: labels.nav.researchGroup,
    items: [
      { to: "/research-hub", label: labels.nav.researchHub },
      { to: "/calibration", label: labels.nav.calibration },
      { to: "/simulator", label: labels.nav.historicalSimulations },
      { to: "/shadow", label: labels.nav.liveExperiment },
      { to: "/research", label: labels.nav.researchLab },
    ],
  },
  {
    title: labels.nav.systemGroup,
    items: [
      { to: "/workflows", label: labels.nav.workflows },
      { to: "/system", label: labels.nav.system },
    ],
  },
];

/** Paths that stay available in USER presentation (soft gate, not security). */
export const USER_ALLOWED_PATH_PREFIXES = [
  "/",
  "/portfolio/mine",
  "/investment-decision",
  "/portfolio-risk",
  "/about",
];

export function navGroupsForRole(role: KrakenPresentationRole): NavGroupDef[] {
  return role === "USER" ? userNav : ownerNav;
}

export function isOwnerOnlyPath(pathname: string): boolean {
  if (pathname === "/" || pathname === "") return false;
  return !USER_ALLOWED_PATH_PREFIXES.some(
    (p) => p !== "/" && (pathname === p || pathname.startsWith(`${p}/`) || pathname.startsWith(`${p}?`)),
  ) && pathname !== "/portfolio/mine";
}

export function pathAllowedForRole(pathname: string, role: KrakenPresentationRole): boolean {
  if (role === "OWNER") return true;
  if (pathname === "/") return true;
  return USER_ALLOWED_PATH_PREFIXES.some((p) => {
    if (p === "/") return pathname === "/";
    return pathname === p || pathname.startsWith(`${p}/`) || pathname.startsWith(`${p}?`);
  });
}
