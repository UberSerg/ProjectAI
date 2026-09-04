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

const primary: NavItem[] = [
  { to: "/", label: labels.nav.overview, end: true },
  { to: "/market", label: labels.nav.market },
];

const analytics: NavItem[] = [
  { to: "/analytics", label: labels.nav.analytics },
  { to: "/relations", label: labels.nav.relations },
  { to: "/technical", label: labels.nav.technical },
  { to: "/recommendations", label: labels.nav.recommendations, soon: true },
  { to: "/models", label: labels.nav.models, soon: true },
  { to: "/decision-memory", label: labels.nav.decisionMemory, soon: true },
];

const trading: NavItem[] = [
  { to: "/shadow", label: labels.nav.liveExperiment },
  { to: "/simulator", label: labels.nav.simulations },
  { to: "/portfolio", label: labels.nav.portfolio, soon: true },
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
              <span className="brand-mark">PA</span>
              <span className="brand-name">ProjectAI</span>
            </div>
            <nav className="sidebar-nav">
              <NavGroup items={primary} />
              <NavGroup title={labels.nav.analytics} items={analytics} />
              <NavGroup title={labels.nav.trading} items={trading} />
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
