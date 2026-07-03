import { Route, Routes } from "react-router-dom";
import OrgListPage from "./pages/OrgListPage";
import OrgEditorPage from "./pages/OrgEditorPage";
import SimulatePage from "./pages/SimulatePage";
import "./App.css";

export default function App() {
  return (
    <div className="app-shell">
      <Routes>
        <Route path="/" element={<OrgListPage />} />
        <Route path="/orgs/:orgId" element={<OrgEditorPage />} />
        <Route path="/orgs/:orgId/simulate" element={<SimulatePage />} />
      </Routes>
    </div>
  );
}
