import { useEffect } from "react";
import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { ToastProvider } from "../components/Toast";
import { HelpProvider } from "../help";
import { RoleModeSwitch } from "../role/RoleModeSwitch";
import { useKrakenRole } from "../role/KrakenRoleContext";
import { labels } from "../utils/labels";
import { navGroupsForRole, pathAllowedForRole, type NavItem } from "./navConfig";

function NavGroup({ title, items }: { title?: string; items: NavItem[] }) {
  return (
    <div className="nav-group">
      {title ? <div className="nav-group-title">{title}</div> : null}
      {items.map((item) => (
        <NavLink
          key={`${item.to}:${item.label}`}
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

function PresentationGate({ children }: { children: React.ReactNode }) {
  const { role } = useKrakenRole();
  const location = useLocation();
  if (!pathAllowedForRole(location.pathname, role)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export function AppShell() {
  const { role, isUser } = useKrakenRole();
  const groups = navGroupsForRole(role);
  const location = useLocation();

  useEffect(() => {
    document.documentElement.dataset.krakenRole = role;
  }, [role]);

  return (
    <ToastProvider>
      <HelpProvider>
        <div
          className="layout"
          data-theme="dark"
          data-product="kraken-personal-v1"
          data-role={role}
        >
          <aside className="sidebar sidebar-compact">
            <div className="brand">
              <span className="brand-mark">K</span>
              <div className="brand-copy">
                <span className="brand-name">Kraken</span>
                <span className="brand-tag">
                  {isUser ? "личный кабинет" : "кабинет владельца"}
                </span>
              </div>
            </div>
            <nav className="sidebar-nav" data-testid="primary-nav" data-role={role}>
              {groups.map((g, idx) => (
                <NavGroup key={g.title ?? `g-${idx}`} title={g.title} items={g.items} />
              ))}
            </nav>
            <RoleModeSwitch />
          </aside>
          <main className="content content-wide" data-layout="wide" data-testid="app-main">
            <PresentationGate key={location.pathname}>
              <Outlet />
            </PresentationGate>
          </main>
        </div>
      </HelpProvider>
    </ToastProvider>
  );
}
