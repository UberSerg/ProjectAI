import { NavLink, Outlet } from "react-router-dom";
import { ToastProvider } from "../components/Toast";
import { HelpProvider } from "../help";
import { labels } from "../utils/labels";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  soon?: boolean;
}

const overview: NavItem[] = [{ to: "/", label: labels.nav.overview, end: true }];

const portfolio: NavItem[] = [
  { to: "/portfolio/candidate", label: labels.nav.portfolioCandidate },
  { to: "/portfolio", label: labels.nav.portfolioHub },
  { to: "/investment-decision", label: labels.nav.investmentDecision },
  { to: "/portfolio-risk", label: labels.nav.portfolioRisk },
  { to: "/allocation", label: labels.nav.allocation },
];

const market: NavItem[] = [
  { to: "/market", label: labels.nav.quotes },
  { to: "/fundamentals", label: labels.nav.fundamentalsShort },
  { to: "/bonds", label: labels.nav.bonds },
];

const research: NavItem[] = [
  { to: "/calibration", label: labels.nav.calibration },
  { to: "/simulator", label: labels.nav.historicalSimulations },
  { to: "/shadow", label: labels.nav.liveExperiment },
  { to: "/analytics", label: labels.nav.analytics },
  { to: "/technical", label: labels.nav.technical },
  { to: "/relations", label: labels.nav.relations },
  { to: "/research", label: labels.nav.researchLab },
  { to: "/models", label: labels.nav.models, soon: true },
  { to: "/recommendations", label: labels.nav.recommendations, soon: true },
  { to: "/decision-memory", label: labels.nav.decisionMemory, soon: true },
];

const system: NavItem[] = [
  { to: "/workflows", label: labels.nav.workflows },
  { to: "/system", label: labels.nav.system },
];

function NavGroup({ title, items }: { title?: string; items: NavItem[] }) {
  return (
    <div className="nav-group">
      {title ? <div className="nav-group-title">{title}</div> : null}
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) => `nav${isActive ? " active" : ""}${item.soon ? " soon" : ""}`}
        >
          <span>{item.label}</span>
          {item.soon ? <em className="soon-tag">{labels.nav.soon}</em> : null}
        </NavLink>
      ))}
    </div>
  );
}

export function AppShell() {
  return (
    <ToastProvider>
      <HelpProvider>
        <div className="layout">
          <aside className="sidebar">
            <div className="brand">
              <span className="brand-mark">K</span>
              <div className="brand-copy">
                <span className="brand-name">Kraken</span>
                <span className="brand-tag">инвестиционный помощник</span>
              </div>
            </div>
            <nav className="sidebar-nav">
              <NavGroup items={overview} />
              <NavGroup title={labels.nav.portfolioGroup} items={portfolio} />
              <NavGroup title={labels.nav.marketGroup} items={market} />
              <NavGroup title={labels.nav.researchGroup} items={research} />
              <NavGroup title={labels.nav.systemGroup} items={system} />
            </nav>
          </aside>
          <main className="content">
            <Outlet />
          </main>
        </div>
      </HelpProvider>
    </ToastProvider>
  );
}
