import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import { formatDateTime } from "../utils/format";

const TIER_COLOR: Record<string, string> = {
  high: "var(--danger)",
  medium: "#d97706",
  low: "var(--success)",
};

export default function DashboardPage() {
  const { orgId: orgIdStr } = useParams();
  const orgId = Number(orgIdStr);

  const [layout, setLayout] = useState<"overview" | "grid">("overview");

  const orgQuery = useQuery({ queryKey: ["org", orgId], queryFn: () => api.getOrg(orgId) });
  const deptsQuery = useQuery({
    queryKey: ["departments", orgId],
    queryFn: () => api.listDepartments(orgId),
  });
  const org = orgQuery.data;
  const depts = deptsQuery.data ?? [];

  const atRiskQuery = useQuery({
    queryKey: ["at-risk", orgId, "all"],
    queryFn: () => api.getAtRisk(orgId, org?.headcount ?? 5000),
    enabled: !!org,
  });
  const employees = atRiskQuery.data?.employees ?? [];

  const trendQuery = useQuery({
    queryKey: ["risk-trend", orgId],
    queryFn: () => api.getRiskTrend(orgId),
  });
  const trend = trendQuery.data ?? [];

  const runsQuery = useQuery({ queryKey: ["runs", orgId, "all"], queryFn: () => api.listRuns(orgId) });
  const runCount = runsQuery.data?.length ?? 0;

  const avgRisk = employees.length
    ? employees.reduce((a, e) => a + e.turnover_probability, 0) / employees.length
    : 0;
  const highCount = employees.filter((e) => e.risk_tier === "high").length;

  const deptName = (id: number) => depts.find((d) => d.id === id)?.name ?? `dept ${id}`;

  const needsAttention = [...employees]
    .sort((a, b) => b.turnover_probability - a.turnover_probability)
    .slice(0, 3);

  const trendData = trend.map((p) => ({
    date: formatDateTime(p.computed_at).split(",")[0],
    risk: Math.round(p.mean_risk * 1000) / 10,
  }));

  const deptCards = depts.map((d) => {
    const deptEmps = employees.filter((e) => e.department_id === d.id);
    const r = deptEmps.length
      ? deptEmps.reduce((a, e) => a + e.turnover_probability, 0) / deptEmps.length
      : 0;
    const tier = r > 0.5 ? "high" : r > 0.25 ? "medium" : "low";
    return { id: d.id, name: d.name, headcount: deptEmps.length, tier, riskPct: Math.round(r * 100) };
  });

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{org?.name ?? "Dashboard"}</h1>
          <p className="page-subtitle">Here's how retention is trending across this org.</p>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Total headcount</div>
          <div className="stat-value">{org?.headcount ?? "—"}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Avg. retention risk</div>
          <div className="stat-value">{(avgRisk * 100).toFixed(0)}%</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">High-risk employees</div>
          <div className="stat-value">{highCount}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Runs logged</div>
          <div className="stat-value">{runCount}</div>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 16 }}>
        <button
          className={`btn${layout === "overview" ? " btn-primary" : ""}`}
          onClick={() => setLayout("overview")}
        >
          Overview
        </button>
        <button
          className={`btn${layout === "grid" ? " btn-primary" : ""}`}
          onClick={() => setLayout("grid")}
        >
          By Department
        </button>
      </div>

      {layout === "overview" && (
        <div className="grid-2">
          <div className="card">
            <h2>Retention risk — recent runs</h2>
            {trend.length === 0 && (
              <p className="muted">
                No runs yet — go run a <Link to={`/orgs/${orgId}/simulate`}>Simulate</Link> to start
                tracking risk over time.
              </p>
            )}
            {trend.length > 0 && (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={trendData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="date" fontSize={11} />
                  <YAxis fontSize={11} unit="%" domain={[0, 100]} />
                  <Tooltip formatter={(v) => [`${v}%`, "Mean risk"]} />
                  <Line type="monotone" dataKey="risk" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="card">
            <h2>Needs attention</h2>
            {needsAttention.length === 0 && <p className="muted">No at-risk data yet.</p>}
            {needsAttention.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {needsAttention.map((e) => (
                  <div key={e.employee_id} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                    <div
                      style={{
                        width: 7, height: 7, borderRadius: "50%", marginTop: 6, flex: "none",
                        background: TIER_COLOR[e.risk_tier],
                      }}
                    />
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>
                        <Link to={`/orgs/${orgId}/employees/${e.employee_id}/risk-history`}>
                          {e.full_name}
                        </Link>
                      </div>
                      <div className="muted">
                        {deptName(e.department_id)} · {(e.turnover_probability * 100).toFixed(0)}% risk
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <Link to={`/orgs/${orgId}/at-risk`} className="btn" style={{ marginTop: 14, width: "100%", textAlign: "center" }}>
              Review at-risk employees
            </Link>
          </div>
        </div>
      )}

      {layout === "grid" && (
        <div className="stat-grid">
          {deptCards.map((d) => (
            <div className="card" key={d.id} style={{ marginBottom: 0 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{d.name}</strong>
                <span className="tag" style={{ color: TIER_COLOR[d.tier], background: "transparent" }}>
                  {d.tier}
                </span>
              </div>
              <p className="muted" style={{ margin: "6px 0 12px" }}>{d.headcount} people</p>
              <div className="risk-bar-track" style={{ width: "100%" }}>
                <div
                  className="risk-bar-fill"
                  style={{ width: `${d.riskPct}%`, background: TIER_COLOR[d.tier] }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
