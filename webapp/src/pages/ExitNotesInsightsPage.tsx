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

const THEME_LABELS: Record<string, string> = {
  workload: "Workload",
  burnout: "Burnout",
  manager_support: "Manager support",
  psychological_safety: "Psychological safety",
  compensation: "Compensation",
  meaning: "Meaning at work",
  sleep_wellbeing: "Sleep & wellbeing",
};

function sentimentColor(s: number): string {
  if (s > 0.15) return "var(--success)";
  if (s < -0.15) return "var(--danger)";
  return "var(--text-3)";
}

export default function ExitNotesInsightsPage() {
  const { orgId: orgIdStr } = useParams();
  const orgId = Number(orgIdStr);

  const orgQuery = useQuery({ queryKey: ["org", orgId], queryFn: () => api.getOrg(orgId) });
  const employeesQuery = useQuery({
    queryKey: ["employees", orgId],
    queryFn: () => api.listEmployees(orgId),
  });
  const insightsQuery = useQuery({
    queryKey: ["exit-notes-insights", orgId],
    queryFn: () => api.getExitNotesInsights(orgId),
  });

  const employees = employeesQuery.data ?? [];
  const employeeName = (id: number | null) => {
    if (id === null) return "— (recovered)";
    return employees.find((e) => e.id === id)?.full_name ?? `Employee ${id}`;
  };

  const insights = insightsQuery.data;
  const themeFrequency = insights?.theme_frequency ?? [];
  const sentimentTrend = insights?.sentiment_trend ?? [];
  const recentQuotes = insights?.recent_quotes ?? [];

  const sentimentChartData = sentimentTrend.map((p, i) => ({
    index: i,
    date: formatDateTime(p.generated_at).split(",")[0],
    sentiment: Math.round(p.mean_sentiment * 100) / 100,
    n_notes: p.n_notes,
  }));

  const maxThemeCount = themeFrequency[0]?.count || 1;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Exit Notes Insights</h1>
          <p className="page-subtitle">
            {orgQuery.data?.name} — recurring themes and sentiment across every exit note ever
            generated for this org's actual quits, trended over time rather than one run at a time.
          </p>
        </div>
      </div>

      {insightsQuery.isLoading && <p className="muted">Loading...</p>}

      {insights && insights.n_notes_total === 0 && (
        <div className="card">
          <p className="muted">
            No exit notes recorded yet for this org. Notes are only generated when a{" "}
            <Link to={`/orgs/${orgId}/simulate`}>Diagnose</Link> run's top-driver segment actually
            has employees quit during that run — build a scenario likely to cause real attrition
            (a layoff, a harsh policy change, a reorg) and run Diagnose to start collecting them.
          </p>
        </div>
      )}

      {insights && insights.n_notes_total > 0 && (
        <>
          <div className="stat-grid">
            <div className="stat-card">
              <div className="stat-label">Notes analyzed</div>
              <div className="stat-value">{insights.n_notes_total}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Overall sentiment</div>
              <div className="stat-value" style={{ color: sentimentColor(insights.mean_sentiment_overall) }}>
                {insights.mean_sentiment_overall >= 0 ? "+" : ""}
                {insights.mean_sentiment_overall.toFixed(2)}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">LLM-written</div>
              <div className="stat-value">{insights.n_llm_generated_total}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Recovered (backfilled)</div>
              <div className="stat-value">{insights.n_backfilled_total}</div>
            </div>
          </div>

          <div className="grid-2">
            <div className="card">
              <h2>Recurring themes</h2>
              <p className="muted" style={{ marginBottom: 12 }}>
                How often each theme shows up across every exit note, ranked by frequency.
              </p>
              {themeFrequency.length === 0 && (
                <p className="muted">No note mentioned any of the tracked themes.</p>
              )}
              {themeFrequency.map((t, i) => (
                <div className="driver-bar-row" key={t.theme}>
                  <div className="driver-bar-labels">
                    <span className="muted">{THEME_LABELS[t.theme] ?? t.theme}</span>
                    <strong>{t.count}</strong>
                  </div>
                  <div className="risk-bar-track" style={{ width: "100%" }}>
                    <div
                      className="risk-bar-fill"
                      style={{
                        width: `${Math.min(100, (t.count / maxThemeCount) * 100)}%`,
                        background: i === 0 ? "var(--danger)" : "var(--accent)",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className="card">
              <h2>Sentiment over time</h2>
              <p className="muted" style={{ marginBottom: 12 }}>
                Mean note sentiment per run that had notes, oldest first.
              </p>
              {sentimentChartData.length === 0 && <p className="muted">Not enough data yet.</p>}
              {sentimentChartData.length > 0 && (
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={sentimentChartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis
                      dataKey="index"
                      fontSize={11}
                      tickFormatter={(i) => sentimentChartData[i]?.date ?? ""}
                    />
                    <YAxis fontSize={11} domain={[-1, 1]} />
                    <Tooltip
                      labelFormatter={(i) => sentimentChartData[i]?.date ?? ""}
                      formatter={(value, name) => [
                        name === "sentiment" ? Number(value).toFixed(2) : value,
                        "Mean sentiment",
                      ]}
                    />
                    <ReferenceLine y={0} stroke="var(--text-3)" strokeDasharray="3 3" />
                    <Line
                      type="monotone" dataKey="sentiment" stroke="var(--accent)"
                      strokeWidth={2} dot={{ r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="card">
            <h2>Recent exit notes</h2>
            <div className="data-list">
              <div className="data-list-scroll">
                <div
                  className="data-list-header"
                  style={{ gridTemplateColumns: "150px 160px 90px 1fr 170px" }}
                >
                  <div>When</div>
                  <div>Employee</div>
                  <div>Sentiment</div>
                  <div>Themes</div>
                  <div>Source</div>
                </div>
                {recentQuotes.map((q) => (
                  <div
                    className="data-list-row"
                    key={q.id}
                    style={{ gridTemplateColumns: "150px 160px 90px 1fr 170px" }}
                  >
                    <div className="data-list-cell">{formatDateTime(q.generated_at)}</div>
                    <div className="data-list-cell">
                      {q.employee_id !== null ? (
                        <Link to={`/orgs/${orgId}/employees/${q.employee_id}/risk-history`}>
                          {employeeName(q.employee_id)}
                        </Link>
                      ) : (
                        <span className="muted">{employeeName(q.employee_id)}</span>
                      )}
                    </div>
                    <div className="data-list-cell" style={{ color: sentimentColor(q.sentiment) }}>
                      {q.sentiment >= 0 ? "+" : ""}
                      {q.sentiment.toFixed(2)}
                    </div>
                    <div className="data-list-cell" title={q.text}>
                      {q.themes.length === 0
                        ? <span className="muted">—</span>
                        : q.themes.map((t) => (
                            <span className="tag" key={t} style={{ marginRight: 4 }}>
                              {THEME_LABELS[t] ?? t}
                            </span>
                          ))}
                    </div>
                    <div className="data-list-cell">
                      <span className="tag">{q.is_llm_generated ? "LLM" : "Template"}</span>
                      {q.is_backfilled && (
                        <span className="tag" style={{ marginLeft: 4, color: "var(--orange)" }}>
                          Recovered
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
