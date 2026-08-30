import { Route, Routes } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { InstrumentPage } from "./pages/InstrumentPage";
import { MarketPage } from "./pages/MarketPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { SystemPage } from "./pages/SystemPage";
import { WorkflowsPage } from "./pages/WorkflowsPage";
import { labels } from "./utils/labels";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/market" element={<MarketPage />} />
        <Route path="/market/instruments/:instrumentId" element={<InstrumentPage />} />
        <Route path="/market/:instrumentId" element={<InstrumentPage />} />
        <Route
          path="/recommendations"
          element={
            <PlaceholderPage
              title={labels.nav.recommendations}
              description="Этот раздел появится после подключения аналитического слоя ProjectAI."
              bullets={["инвестиционные гипотезы", "вероятность сценария", "горизонт", "аргументы моделей"]}
            />
          }
        />
        <Route
          path="/portfolio"
          element={
            <PlaceholderPage
              title={labels.nav.portfolio}
              description="Управление портфелем будет доступно на следующем этапе."
              bullets={["позиции и веса", "ограничения риска", "исполнение сделок"]}
            />
          }
        />
        <Route
          path="/decision-memory"
          element={
            <PlaceholderPage
              title={labels.nav.decisionMemory}
              description="Здесь будет храниться история решений и их исходов."
              bullets={["контекст решения", "обоснование", "результат со временем"]}
            />
          }
        />
        <Route
          path="/models"
          element={
            <PlaceholderPage
              title={labels.nav.models}
              description="Реестр моделей и их статусов появится позже."
              bullets={["версии моделей", "качество прогнозов", "расписание переобучения"]}
            />
          }
        />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/system" element={<SystemPage />} />
      </Route>
    </Routes>
  );
}
