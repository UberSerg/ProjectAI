import { NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { InstrumentPage } from "./pages/InstrumentPage";
import { MarketPage } from "./pages/MarketPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { SystemPage } from "./pages/SystemPage";
import { WorkflowsPage } from "./pages/WorkflowsPage";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/market", label: "Market Data" },
  { to: "/recommendations", label: "Recommendations" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/decision-memory", label: "Decision Memory" },
  { to: "/models", label: "Models" },
  { to: "/workflows", label: "Workflows" },
  { to: "/system", label: "System" },
];

export function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">ProjectAI</div>
        <nav>
          {navItems.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => (isActive ? "nav active" : "nav")}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/market" element={<MarketPage />} />
          <Route path="/market/:instrumentId" element={<InstrumentPage />} />
          <Route path="/recommendations" element={<PlaceholderPage title="Recommendations" />} />
          <Route path="/portfolio" element={<PlaceholderPage title="Portfolio" />} />
          <Route path="/decision-memory" element={<PlaceholderPage title="Decision Memory" />} />
          <Route path="/models" element={<PlaceholderPage title="Models" />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/system" element={<SystemPage />} />
        </Routes>
      </main>
    </div>
  );
}
