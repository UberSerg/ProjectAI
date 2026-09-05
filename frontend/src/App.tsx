import { Route, Routes } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { InstrumentPage } from "./pages/InstrumentPage";
import { MarketPage } from "./pages/MarketPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { RelationsPage } from "./pages/RelationsPage";
import { ResearchComparePage } from "./pages/ResearchComparePage";
import { ResearchDiagnosticsPage } from "./pages/ResearchDiagnosticsPage";
import { ResearchExperimentPage } from "./pages/ResearchExperimentPage";
import { ResearchLabPage } from "./pages/ResearchLabPage";
import { ResearchProspectiveModelsPage } from "./pages/ResearchProspectiveModelsPage";
import { ShadowPage } from "./pages/ShadowPage";
import { SimulatorRunPage } from "./pages/SimulatorRunPage";
import { SimulatorRunsPage } from "./pages/SimulatorRunsPage";
import { SystemPage } from "./pages/SystemPage";
import { TechnicalPage } from "./pages/TechnicalPage";
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
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/relations" element={<RelationsPage />} />
        <Route path="/technical" element={<TechnicalPage />} />
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
        <Route path="/shadow" element={<ShadowPage />} />
        <Route path="/research" element={<ResearchLabPage />} />
        <Route path="/research/compare" element={<ResearchComparePage />} />
        <Route path="/research/diagnostics" element={<ResearchDiagnosticsPage />} />
        <Route path="/research/prospective-models" element={<ResearchProspectiveModelsPage />} />
        <Route path="/research/:runId" element={<ResearchExperimentPage />} />
        <Route path="/simulator" element={<SimulatorRunsPage />} />
        <Route path="/simulator/:runId" element={<SimulatorRunPage />} />
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
