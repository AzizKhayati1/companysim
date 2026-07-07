import { Route, Routes } from "react-router-dom";
import OrgListPage from "./pages/OrgListPage";
import OrgEditorPage from "./pages/OrgEditorPage";
import SimulatePage from "./pages/SimulatePage";
import AtRiskPage from "./pages/AtRiskPage";
import TrainModelPage from "./pages/TrainModelPage";
import RunHistoryPage from "./pages/RunHistoryPage";
import "./App.css";

export default function App() {
  return (
    <div className="app-shell">
      <Routes>
        <Route path="/" element={<OrgListPage />} />
        <Route path="/orgs/:orgId" element={<OrgEditorPage />} />
        <Route path="/orgs/:orgId/simulate" element={<SimulatePage />} />
        <Route path="/orgs/:orgId/at-risk" element={<AtRiskPage />} />
        <Route path="/orgs/:orgId/runs" element={<RunHistoryPage />} />
        <Route path="/model" element={<TrainModelPage />} />
      </Routes>
    </div>
  );
}
