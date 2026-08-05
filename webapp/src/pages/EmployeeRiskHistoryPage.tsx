import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import { formatDateTime } from "../utils/format";
import { buildPromotionMarkers } from "../utils/promotionMarkers";

const TIER_COLOR: Record<string, string> = {
  high: "var(--danger)",
  medium: "var(--orange)",
  low: "var(--success)",
};

const TIER_RECOMMENDATION: Record<string, string> = {
  high: "This person's predicted risk is high. A targeted retention conversation — informed " +
    "by whichever driver below is most elevated — is worth prioritizing before the next cycle.",
  medium: "Risk is moderate and worth watching. A check-in with their manager now can prevent " +
    "it from escalating further.",
  low: "Risk is low. No action needed — continue regular pulse check-ins.",
};

const DRIVER_LABELS: Record<string, string> = {
  workload_perceived: "Workload",
  manager_support_score: "Manager support",
  psychological_safety_perceived: "Psychological safety",
  financial_security_score: "Financial security",
  burnout_exhaustion: "Burnout",
  stress_level: "Stress level",
  mood: "Mood",
  sleep_quality: "Sleep quality",
  meaning_at_work_score: "Meaning at work",
  life_satisfaction: "Life satisfaction",
};

export default function EmployeeRiskHistoryPage() {
  const { orgId: orgIdStr, employeeId: employeeIdStr } = useParams();
  const orgId = Number(orgIdStr);
  const employeeId = Number(employeeIdStr);

  const orgQuery = useQuery({ queryKey: ["org", orgId], queryFn: () => api.getOrg(orgId) });
  const employeesQuery = useQuery({
    queryKey: ["employees", orgId],
    queryFn: () => api.listEmployees(orgId),
  });
  const deptsQuery = useQuery({
    queryKey: ["departments", orgId],
    queryFn: () => api.listDepartments(orgId),
  });
  const teamsQuery = useQuery({
    queryKey: ["teams", orgId],
    queryFn: () => api.listTeams(orgId),
  });
  const historyQuery = useQuery({
    queryKey: ["risk-history", orgId, employeeId],
    queryFn: () => api.getEmployeeRiskHistory(orgId, employeeId),
  });
  const driversQuery = useQuery({
    queryKey: ["risk-drivers", orgId, employeeId],
    queryFn: () => api.getEmployeeRiskDrivers(orgId, employeeId),
  });
  const modelQualityQuery = useQuery({
    queryKey: ["model-quality"],
    queryFn: api.getModelQuality,
  });

  const depts = deptsQuery.data ?? [];
  const teams = teamsQuery.data ?? [];
  const deptName = (id: number) => depts.find((d) => d.id === id)?.name ?? `dept ${id}`;
  const teamName = (id: number) => teams.find((t) => t.id === id)?.name ?? `team ${id}`;

  const employee = employeesQuery.data?.find((e) => e.id === employeeId);
  const points = historyQuery.data ?? [];
  const latest = points[points.length - 1];
  const tier = latest?.risk_tier ?? "low";
  const initials = employee
    ? employee.full_name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase()
    : "--";

  const drivers = driversQuery.data ?? [];

  const chartData = points.map((p, i) => ({
    index: i,
    date: new Date(p.computed_at).toLocaleDateString("en-US"),
    probability: Math.round(p.turnover_probability * 1000) / 10,
  }));
  const promotionMarkers = buildPromotionMarkers(points, modelQualityQuery.data?.history ?? []);

  return (
    <div className="page">
      <Link to={`/orgs/${orgId}/at-risk`} style={{ display: "inline-block", marginBottom: 18 }}>
        &larr; Back to Retention Risk
      </Link>

      <div className="profile-grid">
        <div className="card">
          <div className="profile-avatar">{initials}</div>
          <h2 style={{ marginBottom: 2 }}>{employee?.full_name ?? `Employee ${employeeId}`}</h2>
          <p className="muted" style={{ marginBottom: 14 }}>
            {orgQuery.data?.name}
            {employee && (
              <>
                <br />
                {employee.role} · {deptName(employee.department_id)} · {teamName(employee.team_id)}
              </>
            )}
          </p>
          {latest && (
            <span
              className="tag"
              style={{
                color: TIER_COLOR[tier], background: "transparent", marginBottom: 18,
                display: "inline-block",
              }}
            >
              {tier} risk
            </span>
          )}

          {drivers.length > 0 && (
            <div style={{ marginTop: 18 }}>
              <p className="muted" style={{ marginBottom: 12 }}>
                Ranked by how much each factor is estimated to elevate this person's risk,
                relative to the org average.
              </p>
              {drivers.map((d, i) => (
                <div className="driver-bar-row" key={d.feature}>
                  <div className="driver-bar-labels">
                    <span className="muted">{DRIVER_LABELS[d.feature] ?? d.feature}</span>
                    <strong>
                      {(d.segment_mean * 100).toFixed(0)}%{" "}
                      <span className="muted" style={{ fontWeight: 400 }}>
                        (org avg {(d.org_mean * 100).toFixed(0)}%)
                      </span>
                    </strong>
                  </div>
                  <div className="risk-bar-track" style={{ width: "100%" }}>
                    <div
                      className="risk-bar-fill"
                      style={{
                        width: `${Math.min(100, d.segment_mean * 100)}%`,
                        background: i === 0 ? "var(--danger)" : "var(--orange)",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
          {driversQuery.data && drivers.length === 0 && (
            <p className="muted" style={{ marginTop: 18 }}>
              No driver is meaningfully elevated above the org average for this person.
            </p>
          )}
        </div>

        <div>
          <div className="card">
            <h2 style={{ marginTop: 0 }}>Risk score over time</h2>
            <p className="muted">
              One point per Simulate/Diagnose run against this org, scored at the moment the run
              happened — a rising trend means recent org changes are pushing this person's
              predicted risk up. Dashed lines mark when the production model itself was retrained
              and promoted, which can shift a score even when nothing about this person changed.
            </p>
            {historyQuery.isLoading && <p className="muted">Loading...</p>}
            {!historyQuery.isLoading && points.length === 0 && (
              <p className="muted">
                No runs yet for this org — go run a{" "}
                <Link to={`/orgs/${orgId}/simulate`}>Simulate</Link> or Diagnose first.
              </p>
            )}
            {points.length > 0 && (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis
                    dataKey="index"
                    fontSize={11}
                    tickFormatter={(i) => chartData[i]?.date ?? ""}
                  />
                  <YAxis fontSize={11} unit="%" domain={[0, 100]} />
                  <Tooltip
                    labelFormatter={(i) => chartData[i]?.date ?? ""}
                    formatter={(value) => [`${value}%`, "Turnover probability"]}
                  />
                  {promotionMarkers.map((m) => (
                    <ReferenceLine
                      key={m.index}
                      x={m.index}
                      stroke="var(--text-3)"
                      strokeDasharray="3 3"
                      label={{ value: m.label, position: "top", fontSize: 9, fill: "var(--text-3)" }}
                    />
                  ))}
                  <Line
                    type="monotone"
                    dataKey="probability"
                    stroke={TIER_COLOR[tier]}
                    strokeWidth={2}
                    dot={{ r: 4 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {latest && (
            <div className="card">
              <h2 style={{ marginTop: 0 }}>Recommended next step</h2>
              <p className="muted">{TIER_RECOMMENDATION[tier]}</p>
              <Link to={`/orgs/${orgId}/at-risk`} className="btn btn-primary">
                Open in what-if planner
              </Link>
            </div>
          )}

          {points.length > 0 && (
            <div className="card">
              <h2 style={{ marginTop: 0 }}>Snapshots</h2>
              <div className="data-list">
                <div className="data-list-scroll">
                  <div
                    className="data-list-header"
                    style={{ gridTemplateColumns: "170px 130px 90px 140px" }}
                  >
                    <div>When</div>
                    <div>Risk</div>
                    <div>Tier</div>
                    <div>Source</div>
                  </div>
                  {[...points].reverse().map((p, i) => (
                    <div
                      className="data-list-row"
                      key={`${p.run_id}-${i}`}
                      style={{ gridTemplateColumns: "170px 130px 90px 140px" }}
                    >
                      <div className="data-list-cell">
                        {formatDateTime(p.computed_at)}
                      </div>
                      <div className="data-list-cell">
                        {(p.turnover_probability * 100).toFixed(1)}%
                      </div>
                      <div className="data-list-cell">
                        <span
                          className="tag"
                          style={{ color: TIER_COLOR[p.risk_tier], background: "transparent" }}
                        >
                          {p.risk_tier}
                        </span>
                      </div>
                      <div className="data-list-cell">
                        {p.model_available ? "trained model" : "sim latent (fallback)"}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
