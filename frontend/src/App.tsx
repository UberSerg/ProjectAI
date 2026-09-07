import { Route, Routes } from "react-router-dom";
import { AppShell } from "./layout/AppShell";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { BondsPage } from "./pages/BondsPage";
import { BondDetailPage } from "./pages/BondDetailPage";
import { AllocationPage } from "./pages/AllocationPage";
import { CalibrationPage } from "./pages/CalibrationPage";
import { InvestmentDecisionPage } from "./pages/InvestmentDecisionPage";
import { PortfolioRiskPage } from "./pages/PortfolioRiskPage";
import { DashboardPage } from "./pages/DashboardPage";
import { FundamentalIssuerPage } from "./pages/FundamentalIssuerPage";
import { FundamentalsPage } from "./pages/FundamentalsPage";
import { InstrumentPage } from "./pages/InstrumentPage";
import { InstrumentCatalogDetailPage, InstrumentsPage } from "./pages/InstrumentsPage";
import { MarketPage } from "./pages/MarketPage";
import { MyPortfolioPage } from "./pages/MyPortfolioPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { PortfolioCandidatePage } from "./pages/PortfolioCandidatePage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { RelationsPage } from "./pages/RelationsPage";
import { ResearchAdvancedPage } from "./pages/ResearchAdvancedPage";
import { ResearchComparePage } from "./pages/ResearchComparePage";
import { ResearchDiagnosticsPage } from "./pages/ResearchDiagnosticsPage";
import { ResearchExperimentPage } from "./pages/ResearchExperimentPage";
import { ResearchHubPage } from "./pages/ResearchHubPage";
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
        <Route path="/instruments" element={<InstrumentsPage />} />
        <Route path="/instruments/:secid" element={<InstrumentCatalogDetailPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/relations" element={<RelationsPage />} />
        <Route path="/technical" element={<TechnicalPage />} />
        <Route path="/fundamentals" element={<FundamentalsPage />} />
        <Route path="/companies" element={<FundamentalsPage />} />
        <Route path="/bonds" element={<BondsPage />} />
        <Route path="/bonds/:secid" element={<BondDetailPage />} />
        <Route path="/allocation" element={<AllocationPage />} />
        <Route path="/investment-decision" element={<InvestmentDecisionPage />} />
        <Route path="/calibration" element={<CalibrationPage />} />
        <Route path="/portfolio-risk" element={<PortfolioRiskPage />} />
        <Route path="/fundamentals/:issuerId" element={<FundamentalIssuerPage />} />
        <Route path="/companies/:issuerId" element={<FundamentalIssuerPage />} />
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
        <Route path="/research-hub" element={<ResearchHubPage />} />
        <Route path="/research/advanced" element={<ResearchAdvancedPage />} />
        <Route path="/research/compare" element={<ResearchComparePage />} />
        <Route path="/research/diagnostics" element={<ResearchDiagnosticsPage />} />
        <Route path="/research/prospective-models" element={<ResearchProspectiveModelsPage />} />
        <Route path="/research/:runId" element={<ResearchExperimentPage />} />
        <Route path="/research" element={<ResearchLabPage />} />
        <Route path="/simulator" element={<SimulatorRunsPage />} />
        <Route path="/simulator/:runId" element={<SimulatorRunPage />} />
        <Route path="/portfolio" element={<PortfolioPage />} />
        <Route path="/portfolio/mine" element={<MyPortfolioPage />} />
        <Route path="/portfolio/candidate" element={<PortfolioCandidatePage />} />
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
