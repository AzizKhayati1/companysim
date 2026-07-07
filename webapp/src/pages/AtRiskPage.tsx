import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { InterventionType } from "../types";

const INTERVENTIONS: { value: InterventionType; label: string; magnitudeLabel: string }[] = [
  { value: "retention_bonus", label: "Retention Bonus", magnitudeLabel: "Amount %" },
  { value: "workload_relief", label: "Workload Relief", magnitudeLabel: "Delta" },
  { value: "manager_coaching", label: "Manager Coaching", magnitudeLabel: "Delta" },
];

const TIER_COLOR: Record<string, string> = {
  high: "var(--danger)",
  medium: "#d97706",
  low: "var(--success)",
};

export default function AtRiskPage() {
  const { orgId: orgIdStr } = useParams();
  const orgId = Number(orgIdStr);

  const orgQuery = useQuery({ queryKey: ["org", orgId], queryFn: () => api.getOrg(orgId) });
  const deptsQuery = useQuery({
    queryKey: ["departments", orgId],
    queryFn: () => api.listDepartments(orgId),
  });
  const teamsQuery = useQuery({
    queryKey: ["teams", orgId],
    queryFn: () => api.listTeams(orgId),
  });
  const depts = deptsQuery.data ?? [];
  const teams = teamsQuery.data ?? [];
  const deptName = (id: number) => depts.find((d) => d.id === id)?.name ?? `dept ${id}`;
  const teamName = (id: number) => teams.find((t) => t.id === id)?.name ?? `team ${id}`;

  const [rankSize, setRankSize] = useState(50);
  const atRiskQuery = useQuery({
    queryKey: ["at-risk", orgId, rankSize],
    queryFn: () => api.getAtRisk(orgId, rankSize),
  });

  const [interventionType, setInterventionType] = useState<InterventionType>("retention_bonus");
  const [topK, setTopK] = useState(20);
  const [magnitude, setMagnitude] = useState(0.15);
  const [horizonTicks, setHorizonTicks] = useState(12);
  const [replicates, setReplicates] = useState(15);
  const [seed, setSeed] = useState(5000);

  const compareMutation = useMutation({
    mutationFn: () => {
      const params =
        interventionType === "retention_bonus" ? { amount_pct: magnitude } : { delta: magnitude };
      return api.compareIntervention(orgId, {
        intervention_type: interventionType,
        top_k: topK,
        at_tick: 1,
        params,
        horizon_ticks: horizonTicks,
        replicates,
        seed,
      });
    },
  });

  const employees = atRiskQuery.data?.employees ?? [];
  const result = compareMutation.data;
  const activeIntervention = INTERVENTIONS.find((i) => i.value === interventionType)!;

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 16 }}>
        <Link to="/">&larr; All orgs</Link>
        <Link to={`/orgs/${orgId}`}>Edit org</Link>
        <Link to={`/orgs/${orgId}/simulate`}>Simulate</Link>
      </div>
      <h1>At-Risk Employees — {orgQuery.data?.name}</h1>
      <p className="muted">
        Who's likely to leave, and does a targeted intervention actually reduce it? Ranked by
        the trained turnover model when one is available; falls back to the simulation's own
        risk estimate otherwise.
      </p>

      {atRiskQuery.data && !atRiskQuery.data.model_available && (
        <div className="card" style={{ borderColor: "#d97706" }}>
          <p className="muted">
            No trained turnover model found (<code>models/turnover_production.joblib</code>) —
            ranking falls back to the simulation's internal risk score rather than a real
            prediction. Run <code>scripts/train_turnover_model.py</code> for model-based ranking.
          </p>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Ranked employees</h2>
          <label>
            Show top{" "}
            <input
              type="number"
              min={5}
              max={500}
              value={rankSize}
              onChange={(e) => setRankSize(Number(e.target.value))}
            />
          </label>
        </div>
        {atRiskQuery.isLoading && <p className="muted">Scoring...</p>}
        {atRiskQuery.isError && <p className="error">{(atRiskQuery.error as Error).message}</p>}
        {employees.length > 0 && (
          <div className="data-list">
            <div className="data-list-scroll">
              <div
                className="data-list-header"
                style={{ gridTemplateColumns: "1fr 150px 150px 70px 130px 90px" }}
              >
                <div>Name</div>
                <div>Department</div>
                <div>Team</div>
                <div>Level</div>
                <div>Risk</div>
                <div>Tier</div>
              </div>
              {employees.map((e) => (
                <div
                  className="data-list-row"
                  key={e.employee_id}
                  style={{ gridTemplateColumns: "1fr 150px 150px 70px 130px 90px" }}
                >
                  <div className="data-list-cell">{e.full_name}</div>
                  <div className="data-list-cell">{deptName(e.department_id)}</div>
                  <div className="data-list-cell">{teamName(e.team_id)}</div>
                  <div className="data-list-cell">{e.level}</div>
                  <div className="data-list-cell row" style={{ gap: 8, flexWrap: "nowrap" }}>
                    <div className="risk-bar-track">
                      <div
                        className="risk-bar-fill"
                        style={{
                          width: `${Math.min(100, e.turnover_probability * 100)}%`,
                          background: TIER_COLOR[e.risk_tier],
                        }}
                      />
                    </div>
                    <span>{(e.turnover_probability * 100).toFixed(1)}%</span>
                  </div>
                  <div className="data-list-cell">
                    <span
                      className="tag"
                      style={{ color: TIER_COLOR[e.risk_tier], background: "transparent" }}
                    >
                      {e.risk_tier}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2>What-if: apply an intervention to the top-K at-risk employees</h2>
        <div className="row">
          <label>
            Intervention{" "}
            <select
              value={interventionType}
              onChange={(e) => setInterventionType(e.target.value as InterventionType)}
            >
              {INTERVENTIONS.map((i) => (
                <option key={i.value} value={i.value}>{i.label}</option>
              ))}
            </select>
          </label>
          <label>
            Target top-K at-risk{" "}
            <input type="number" min={1} max={500} value={topK}
              onChange={(e) => setTopK(Number(e.target.value))} />
          </label>
          <label>
            {activeIntervention.magnitudeLabel}{" "}
            <input type="number" min={0} max={1} step="0.05" value={magnitude}
              onChange={(e) => setMagnitude(Number(e.target.value))} />
          </label>
          <label>
            Horizon (weeks){" "}
            <input type="number" min={4} max={30} value={horizonTicks}
              onChange={(e) => setHorizonTicks(Number(e.target.value))} />
          </label>
          <label>
            Replicates{" "}
            <input type="number" min={5} max={50} value={replicates}
              onChange={(e) => setReplicates(Number(e.target.value))} />
          </label>
          <label>
            Seed{" "}
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
          </label>
        </div>
        <button
          className="btn btn-primary"
          style={{ marginTop: 10 }}
          disabled={compareMutation.isPending}
          onClick={() => compareMutation.mutate()}
        >
          {compareMutation.isPending ? "Running..." : "Compare with / without intervention"}
        </button>
        {compareMutation.isError && (
          <p className="error">{(compareMutation.error as Error).message}</p>
        )}

        {result && (
          <div style={{ marginTop: 16 }}>
            <div className="stat-grid">
              <div className="stat-card">
                <div className="stat-label">Targeted cohort</div>
                <div className="stat-value">{result.target_employee_count}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Baseline quits (median)</div>
                <div className="stat-value">{result.baseline_target_quits_p50.toFixed(1)}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Treated quits (median)</div>
                <div className="stat-value">{result.treated_target_quits_p50.toFixed(1)}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Estimated cost</div>
                <div className="stat-value">
                  ${result.estimated_cost.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                </div>
              </div>
            </div>
            <p>
              <strong>Quits avoided</strong> — mean {result.quits_avoided_mean.toFixed(2)},
              median {result.quits_avoided_p50.toFixed(1)} (p05&ndash;p95:{" "}
              {result.quits_avoided_p05.toFixed(1)} to {result.quits_avoided_p95.toFixed(1)})
            </p>
            <p className="muted">
              Small targeted cohorts produce noisy, discrete per-replicate counts — treat the
              band, not the point estimate, as the answer.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
