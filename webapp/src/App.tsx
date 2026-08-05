import { Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import OrgListPage from "./pages/OrgListPage";
import DashboardPage from "./pages/DashboardPage";
import OrgEditorPage from "./pages/OrgEditorPage";
import SimulatePage from "./pages/SimulatePage";
import AtRiskPage from "./pages/AtRiskPage";
import TrainModelPage from "./pages/TrainModelPage";
import RunHistoryPage from "./pages/RunHistoryPage";
import EmployeeRiskHistoryPage from "./pages/EmployeeRiskHistoryPage";
import ExitNotesInsightsPage from "./pages/ExitNotesInsightsPage";
import DocumentsPage from "./pages/DocumentsPage";
import "./App.css";

export default function App() {
  return (
    <div className="app-shell">
      <Routes>
        <Route path="/" element={<OrgListPage />} />
        <Route element={<AppShell />}>
          <Route path="/orgs/:orgId" element={<DashboardPage />} />
          <Route path="/orgs/:orgId/editor" element={<OrgEditorPage />} />
          <Route path="/orgs/:orgId/simulate" element={<SimulatePage />} />
          <Route path="/orgs/:orgId/at-risk" element={<AtRiskPage />} />
          <Route path="/orgs/:orgId/exit-notes" element={<ExitNotesInsightsPage />} />
          <Route path="/orgs/:orgId/documents" element={<DocumentsPage />} />
          <Route path="/orgs/:orgId/runs" element={<RunHistoryPage />} />
          <Route
            path="/orgs/:orgId/employees/:employeeId/risk-history"
            element={<EmployeeRiskHistoryPage />}
          />
          <Route path="/model" element={<TrainModelPage />} />
        </Route>
      </Routes>
    </div>
  );
}
