import { NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/DashboardPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/recommendations", label: "Recommendations" },
  { to: "/market", label: "Market" },
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
          <Route path="/recommendations" element={<PlaceholderPage title="Recommendations" />} />
          <Route path="/market" element={<PlaceholderPage title="Market" />} />
          <Route path="/portfolio" element={<PlaceholderPage title="Portfolio" />} />
          <Route path="/decision-memory" element={<PlaceholderPage title="Decision Memory" />} />
          <Route path="/models" element={<PlaceholderPage title="Models" />} />
          <Route path="/workflows" element={<PlaceholderPage title="Workflows" />} />
          <Route path="/system" element={<PlaceholderPage title="System" />} />
        </Routes>
      </main>
    </div>
  );
}
