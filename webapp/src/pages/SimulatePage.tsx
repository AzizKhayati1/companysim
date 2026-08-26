import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useLocation, useParams } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import DiagnosisResults from "../components/DiagnosisResults";
import Modal from "../components/Modal";
import SimulationResults from "../components/SimulationResults";
import {
  EVENT_TYPE_LABELS,
  LEVELS,
  LIFE_EVENT_TYPES,
  type DepartmentOut,
  type DiagnosisReportOut,
  type ScenarioEventIn,
  type ScenarioEventType,
  type SimulateRequest,
} from "../types";
import { buildEventMarkers } from "../utils/eventMarkers";

const DEFAULT_TICKS = 12;
const DEFAULT_REPLICATES = 1;
const DEFAULT_SEED = 1234;

const EVENT_TYPES: { value: ScenarioEventType; label: string; group: string }[] = [
  { value: "layoff", label: "Layoff", group: "Global" },
  { value: "hire", label: "Hire", group: "Global" },
  { value: "promotion", label: "Promotion", group: "Global" },
  { value: "policy_change", label: "Policy Change", group: "Global" },
  { value: "budget_cut", label: "Budget Cut", group: "Global" },
  { value: "reorg", label: "Reorg", group: "Global" },
  { value: "retention_bonus", label: "Retention Bonus", group: "Targeted" },
  { value: "workload_relief", label: "Workload Relief", group: "Targeted" },
  { value: "manager_coaching", label: "Manager Coaching", group: "Targeted" },
  { value: "termination", label: "Termination", group: "Targeted" },
  { value: "transfer", label: "Transfer", group: "Targeted" },
  { value: "life_event", label: "Life Event (outside work)", group: "Outside work" },
];

// Canned playbooks for the 6 "Global" event types only — those apply to a
// department or the whole org, so a template can fire immediately with
// sensible defaults. Targeted/life-event types inherently need specific
// employees picked, so they stay manual.
const SCENARIO_TEMPLATES: {
  label: string;
  description: string;
  build: (depts: DepartmentOut[]) => ScenarioEventIn[];
}[] = [
  {
    label: "Layoff wave", description: "15% org-wide reduction",
    build: () => [{ type: "layoff", at_tick: 1, params: { fraction: 0.15 } }],
  },
  {
    label: "Budget tightening", description: "Org-wide budget cut",
    build: () => [{ type: "budget_cut", at_tick: 1, params: { severity: 0.25 } }],
  },
  {
    label: "Reorg shake-up", description: "Org-wide restructuring",
    build: () => [{ type: "reorg", at_tick: 1, params: { delta: 0.15 } }],
  },
  {
    label: "Policy overhaul", description: "Org-wide policy change",
    build: () => [{ type: "policy_change", at_tick: 1, params: { delta: 0.15 } }],
  },
  {
    label: "Promotion cycle", description: "15 IC2s promoted",
    build: () => [{ type: "promotion", at_tick: 1, params: { count: 15, from_level: "IC2" } }],
  },
  {
    label: "Hiring wave", description: "5 new hires per department",
    build: (depts) => depts.map((d) => ({
      type: "hire" as ScenarioEventType, at_tick: 1, params: { count: 5, department_id: d.id },
    })),
  },
];

/** Event params as a sentence fragment instead of raw JSON.
 *
 * The editor previously printed JSON.stringify(e.params) into a cell —
 * accurate, and unreadable. Ids are resolved to the names they stand for,
 * because "dept 73" tells a reviewer nothing they can act on. Unknown
 * keys still render, humanised, rather than being dropped: a scenario the
 * UI does not recognise must still be inspectable. */
function describeParams(
  params: Record<string, unknown>,
  depts: DepartmentOut[],
  emps: { id: number; full_name: string }[],
): string {
  const name = (list: { id: number }[], id: unknown, get: (x: never) => string) => {
    const hit = list.find((x) => x.id === Number(id));
    return hit ? get(hit as never) : String(id);
  };
  return Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => {
      if (k === "department_id") return name(depts, v, (d: DepartmentOut) => d.name);
      if (k === "employee_id") return name(emps, v, (e: { full_name: string }) => e.full_name);
      const label = k.replace(/_/g, " ");
      if (typeof v === "boolean") return v ? label : `no ${label}`;
      return `${label} ${v}`;
    })
    .join(" · ");
}

export default function SimulatePage() {
  const { orgId: orgIdStr } = useParams();
  const orgId = Number(orgIdStr);
  const location = useLocation();
  const loadedRequest = (location.state as { loadedRequest?: SimulateRequest } | null)?.loadedRequest;

  const orgQuery = useQuery({ queryKey: ["org", orgId], queryFn: () => api.getOrg(orgId) });
  const deptsQuery = useQuery({
    queryKey: ["departments", orgId],
    queryFn: () => api.listDepartments(orgId),
  });
  const teamsQuery = useQuery({
    queryKey: ["teams", orgId],
    queryFn: () => api.listTeams(orgId),
  });
  const empsQuery = useQuery({
    queryKey: ["employees", orgId],
    queryFn: () => api.listEmployees(orgId),
  });
  const depts = deptsQuery.data ?? [];
  const teams = teamsQuery.data ?? [];
  const emps = empsQuery.data ?? [];

  const [ticks, setTicks] = useState(loadedRequest?.ticks ?? DEFAULT_TICKS);
  const [replicates, setReplicates] = useState(loadedRequest?.replicates ?? DEFAULT_REPLICATES);
  const [seed, setSeed] = useState(loadedRequest?.seed ?? DEFAULT_SEED);
  const [events, setEvents] = useState<ScenarioEventIn[]>(loadedRequest?.events ?? []);
  const [showLoadedBanner, setShowLoadedBanner] = useState(loadedRequest !== undefined);

  const [newType, setNewType] = useState<ScenarioEventType>("layoff");
  const [atTick, setAtTick] = useState(1);
  const [fraction, setFraction] = useState(0.1);
  const [count, setCount] = useState(10);
  const [fromLevel, setFromLevel] = useState<string>("IC2");
  const [delta, setDelta] = useState(0.1);
  const [severity, setSeverity] = useState(0.2);
  const [amountPct, setAmountPct] = useState(0.1);
  const [deptId, setDeptId] = useState<number | "">("");
  const [teamId, setTeamId] = useState<number | "">("");
  const [selectedEmpIds, setSelectedEmpIds] = useState<number[]>([]);
  const [lifeEventType, setLifeEventType] = useState<string>(LIFE_EVENT_TYPES[0]);

  const simulateMutation = useMutation({
    mutationFn: () => api.simulate(orgId, { ticks, replicates, seed, events }),
  });
  // Forecast chart is always a clean single-run baseline-vs-treated
  // comparison, independent of whatever `replicates` is set to for the
  // full Monte Carlo results below.
  const forecastMutation = useMutation({
    mutationFn: async () => {
      const [baseline, treated] = await Promise.all([
        api.simulate(orgId, { ticks, replicates: 1, seed, events: [] }),
        api.simulate(orgId, { ticks, replicates: 1, seed, events }),
      ]);
      return { baseline, treated };
    },
  });
  // The report opens over the page rather than appending below it, so
  // dismissing is free and the scenario keeps its scroll and its state.
  const [diagnosisOpen, setDiagnosisOpen] = useState(false);
  const diagnoseMutation = useMutation({
    mutationFn: () => api.diagnose(orgId, { ticks, replicates: 1, seed, events }),
    onSuccess: () => setDiagnosisOpen(true),
  });
  const exportPdfMutation = useMutation({
    mutationFn: async () => {
      const blob = await api.exportDiagnosisPdf(orgId, { ticks, replicates: 1, seed, events });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `diagnosis_org_${orgId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    },
  });

  const addEvent = () => {
    let params: Record<string, unknown> = {};
    if (newType === "layoff") params = { fraction, department_id: deptId || undefined };
    if (newType === "hire") params = { count, department_id: deptId };
    if (newType === "promotion") params = { count, from_level: fromLevel };
    if (newType === "policy_change") params = { delta, department_id: deptId || undefined };
    if (newType === "budget_cut") params = { severity, department_id: deptId || undefined };
    if (newType === "reorg") params = { delta, department_id: deptId || undefined };
    if (newType === "retention_bonus") params = { employee_ids: selectedEmpIds, amount_pct: amountPct };
    if (newType === "workload_relief") params = { employee_ids: selectedEmpIds, delta };
    if (newType === "manager_coaching") params = { team_id: teamId, delta };
    if (newType === "termination") params = { employee_ids: selectedEmpIds };
    if (newType === "transfer") params = { employee_ids: selectedEmpIds, new_team_id: teamId };
    if (newType === "life_event") params = { employee_ids: selectedEmpIds, event_type: lifeEventType };
    setEvents([...events, { type: newType, at_tick: atTick, params }]);
  };

  const applyRecommendation = (report: DiagnosisReportOut) => {
    const rec = report.recommendation;
    const params: Record<string, unknown> = { ...rec.suggested_params };
    if (rec.event_type === "manager_coaching" && rec.target_team) {
      params.team_id = rec.target_team;
    } else if (rec.target_employee_ids.length > 0) {
      params.employee_ids = rec.target_employee_ids;
    }
    setEvents([...events, {
      type: rec.event_type as ScenarioEventType,
      at_tick: report.problem.tick,
      params,
    }]);
  };

  const runAll = () => {
    simulateMutation.mutate();
    forecastMutation.mutate();
  };

  const resetToDefaults = () => {
    setTicks(DEFAULT_TICKS);
    setReplicates(DEFAULT_REPLICATES);
    setSeed(DEFAULT_SEED);
    setEvents([]);
    setShowLoadedBanner(false);
  };

  const result = simulateMutation.data;
  const diagnosis = diagnoseMutation.data;
  const forecast = forecastMutation.data;

  const forecastData = forecast
    ? forecast.baseline.rows.map((row, i) => ({
        tick: row.tick as number,
        baseline: Math.round((row.mean_turnover_risk as number) * 1000) / 10,
        treated: Math.round(((forecast.treated.rows[i]?.mean_turnover_risk as number) ?? 0) * 1000) / 10,
      }))
    : [];
  const forecastMarkers = buildEventMarkers(events, EVENT_TYPE_LABELS);

  return (
    <div className="page">
      {/* The run controls used to sit at the bottom of a form long enough
          to scroll past. Editing an event and running it are one loop, so
          the action belongs where it is always reachable — and the header
          is the only place on the page that never moves. */}
      <div className="page-header">
        <div>
          <div className="page-eyebrow">Plan · Scenario Simulator</div>
          <h1 className="page-title">
            {events.length === 0
              ? "Model a change before you make it"
              : `${events.length} ${events.length === 1 ? "change" : "changes"} over ${ticks} weeks`}
          </h1>
          <p className="page-subtitle">
            {orgQuery.data?.name} — forecast the effect on retention risk before you act.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn"
            disabled={exportPdfMutation.isPending}
            onClick={() => exportPdfMutation.mutate()}
          >
            {exportPdfMutation.isPending ? "Exporting..." : "Export PDF"}
          </button>
          <button
            className="btn"
            disabled={diagnoseMutation.isPending}
            onClick={() => diagnoseMutation.mutate()}
          >
            {diagnoseMutation.isPending ? "Diagnosing..." : "Diagnose"}
          </button>
          <button
            className="btn btn-primary"
            disabled={simulateMutation.isPending || forecastMutation.isPending}
            onClick={runAll}
          >
            {simulateMutation.isPending ? "Running..." : "Run forecast"}
          </button>
        </div>
      </div>

      {showLoadedBanner && (
        <div
          className="card"
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            borderColor: "var(--accent)", marginBottom: 20,
          }}
        >
          <p className="muted" style={{ margin: 0 }}>
            Loaded a saved scenario from Run History — edit events below and re-run to save it as
            a new run, or start over.
          </p>
          <button className="btn" onClick={resetToDefaults}>Start fresh</button>
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h2>Build a scenario</h2>
          <div className="field-group-label">Horizon</div>
          <div className="row" style={{ marginBottom: 14 }}>
            <label>
              Ticks{" "}
              <input type="number" min={1} max={80} value={ticks}
                onChange={(e) => setTicks(Number(e.target.value))} />
            </label>
            <label>
              Replicates (&gt;1 = Monte Carlo bands){" "}
              <input type="number" min={1} max={50} value={replicates}
                onChange={(e) => setReplicates(Number(e.target.value))} />
            </label>
            <label>
              Seed{" "}
              <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
            </label>
          </div>

          <p className="muted">
            Global levers affect a department or the whole org; targeted levers hit named
            employees; life events model things happening outside work.
          </p>

          <div className="field-group-label">Start from a template</div>
          <div className="row" style={{ marginBottom: 14, flexWrap: "wrap" }}>
            {SCENARIO_TEMPLATES.map((t) => (
              <button
                key={t.label}
                className="btn"
                title={t.description}
                onClick={() => setEvents([...events, ...t.build(depts)])}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="field-group-label">
            Timeline{events.length > 0 && ` · ${events.length} ${events.length === 1 ? "change" : "changes"}`}
          </div>

          {events.length === 0 && (
            <p className="sim-empty">
              No changes yet. Start from a template above, or add one below — a scenario with no
              events forecasts the org as it stands.
            </p>
          )}

          {events.length > 0 && (
            <>
              {/* Events carry a tick, so their position in time is real
                  information. A table sorts it into a column and makes you
                  reconstruct the shape; the track shows clustering and gaps
                  at a glance. */}
              <div className="sim-track" aria-hidden="true">
                <div className="sim-track-line" />
                {events.map((e, i) => (
                  <div
                    key={i}
                    className="sim-track-pin"
                    style={{ left: `${Math.min(100, (e.at_tick / Math.max(ticks, 1)) * 100)}%` }}
                    title={`${EVENT_TYPE_LABELS[e.type] ?? e.type} at week ${e.at_tick}`}
                  />
                ))}
                <div className="sim-track-scale">
                  <span>week 0</span>
                  <span>week {ticks}</span>
                </div>
              </div>

              <div className="sim-events">
                {events.map((e, i) => (
                  <div className="sim-event" key={i}>
                    <div className="sim-event-tick">w{e.at_tick}</div>
                    <div className="sim-event-body">
                      <div className="sim-event-type">{EVENT_TYPE_LABELS[e.type] ?? e.type}</div>
                      {describeParams(e.params, depts, emps) && (
                        <div className="sim-event-params">{describeParams(e.params, depts, emps)}</div>
                      )}
                    </div>
                    <button
                      className="sim-event-remove"
                      aria-label={`Remove ${EVENT_TYPE_LABELS[e.type] ?? e.type} at week ${e.at_tick}`}
                      onClick={() => setEvents(events.filter((_, j) => j !== i))}
                    >
                      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.9"
                           strokeLinecap="round" aria-hidden="true">
                        <path d="M6 6l8 8M14 6l-8 8" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="field-group-label" style={{ marginTop: 18 }}>Add a change</div>

          <div className="row">
            <label>
              Type{" "}
              <select value={newType} onChange={(e) => setNewType(e.target.value as ScenarioEventType)}>
                {["Global", "Targeted", "Outside work"].map((group) => (
                  <optgroup label={group} key={group}>
                    {EVENT_TYPES.filter((t) => t.group === group).map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label>
              At tick{" "}
              <input type="number" min={0} value={atTick} onChange={(e) => setAtTick(Number(e.target.value))} />
            </label>

            {(newType === "layoff" || newType === "hire" || newType === "policy_change" ||
              newType === "budget_cut" || newType === "reorg") && (
              <label>
                Department (optional except Hire){" "}
                <select value={deptId} onChange={(e) => setDeptId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">All departments</option>
                  {depts.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>
              </label>
            )}

            {newType === "layoff" && (
              <label>
                Fraction{" "}
                <input type="number" min={0} max={1} step="0.05" value={fraction}
                  onChange={(e) => setFraction(Number(e.target.value))} />
              </label>
            )}
            {(newType === "hire" || newType === "promotion") && (
              <label>
                Count{" "}
                <input type="number" min={1} value={count} onChange={(e) => setCount(Number(e.target.value))} />
              </label>
            )}
            {newType === "promotion" && (
              <label>
                From level{" "}
                <select value={fromLevel} onChange={(e) => setFromLevel(e.target.value)}>
                  {LEVELS.map((l) => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </label>
            )}
            {(newType === "policy_change" || newType === "workload_relief" ||
              newType === "manager_coaching" || newType === "reorg") && (
              <label>
                Delta{" "}
                <input type="number" step="0.05" value={delta} onChange={(e) => setDelta(Number(e.target.value))} />
              </label>
            )}
            {newType === "budget_cut" && (
              <label>
                Severity{" "}
                <input type="number" min={0} max={1} step="0.05" value={severity}
                  onChange={(e) => setSeverity(Number(e.target.value))} />
              </label>
            )}
            {newType === "retention_bonus" && (
              <label>
                Amount %{" "}
                <input type="number" min={0} max={1} step="0.05" value={amountPct}
                  onChange={(e) => setAmountPct(Number(e.target.value))} />
              </label>
            )}
            {(newType === "manager_coaching" || newType === "transfer") && (
              <label>
                {newType === "transfer" ? "New team" : "Team"}{" "}
                <select value={teamId} onChange={(e) => setTeamId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Choose team...</option>
                  {teams.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </label>
            )}
            {newType === "life_event" && (
              <label>
                Life event type{" "}
                <select value={lifeEventType} onChange={(e) => setLifeEventType(e.target.value)}>
                  {LIFE_EVENT_TYPES.map((t) => (
                    <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </label>
            )}
            {(newType === "retention_bonus" || newType === "workload_relief" ||
              newType === "termination" || newType === "transfer" || newType === "life_event") && (
              <label>
                Target employees{" "}
                <select
                  multiple
                  size={4}
                  style={{ minWidth: 180 }}
                  value={selectedEmpIds.map(String)}
                  onChange={(e) =>
                    setSelectedEmpIds(Array.from(e.target.selectedOptions).map((o) => Number(o.value)))
                  }
                >
                  {emps.map((emp) => (
                    <option key={emp.id} value={emp.id}>{emp.full_name}</option>
                  ))}
                </select>
              </label>
            )}
            <button className="btn" onClick={addEvent}>+ Add event</button>
          </div>

          {simulateMutation.isError && (
            <p className="error">{(simulateMutation.error as Error).message}</p>
          )}
          {diagnoseMutation.isError && (
            <p className="error">{(diagnoseMutation.error as Error).message}</p>
          )}
          {exportPdfMutation.isError && (
            <p className="error">{(exportPdfMutation.error as Error).message}</p>
          )}
        </div>

        <div className="card">
          <h2>Projected retention risk — next {ticks} weeks</h2>
          {!forecast && !forecastMutation.isPending && (
            <p className="muted">
              Build a scenario and click "Run forecast" to compare baseline vs. with-scenario
              retention risk over time.
            </p>
          )}
          {forecastMutation.isPending && <p className="muted">Forecasting...</p>}
          {forecast && (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={forecastData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="tick" fontSize={11} />
                <YAxis fontSize={11} unit="%" />
                <Tooltip formatter={(v) => `${v}%`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {forecastMarkers.map((m) => (
                  <ReferenceLine
                    key={m.at_tick}
                    x={m.at_tick}
                    stroke="var(--text-3)"
                    strokeDasharray="3 3"
                    label={{ value: m.label, position: "top", fontSize: 9, fill: "var(--text-3)" }}
                  />
                ))}
                <Line
                  type="monotone" dataKey="baseline" name="Baseline" stroke="var(--text-3)"
                  strokeWidth={2} strokeDasharray="4 4" dot={false}
                />
                <Line
                  type="monotone" dataKey="treated" name="With scenario" stroke="var(--accent)"
                  strokeWidth={2} dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {diagnosis && diagnosisOpen && (
        <Modal
          title="Diagnosis"
          subtitle={`${ticks} weeks · ${events.length} ${events.length === 1 ? "change" : "changes"} · seed ${seed}`}
          onClose={() => setDiagnosisOpen(false)}
          footer={
            <>
              <button className="btn" onClick={() => setDiagnosisOpen(false)}>Close</button>
              <button
                className="btn"
                disabled={exportPdfMutation.isPending}
                onClick={() => exportPdfMutation.mutate()}
              >
                {exportPdfMutation.isPending ? "Exporting..." : "Export PDF"}
              </button>
            </>
          }
        >
          <DiagnosisResults
            diagnosis={diagnosis}
            depts={depts}
            teams={teams}
            onApplyRecommendation={(report) => {
              applyRecommendation(report);
              // Applying writes an event into the scenario behind, so the
              // report has served its purpose — leaving it up would hide
              // the change the user just made.
              setDiagnosisOpen(false);
            }}
          />
        </Modal>
      )}

      {diagnosis && !diagnosisOpen && (
        <div className="reopen-strip">
          <span>A diagnosis from the last run is available.</span>
          <button className="btn" onClick={() => setDiagnosisOpen(true)}>Show it</button>
        </div>
      )}

      {result && <SimulationResults result={result} events={events} />}
    </div>
  );
}
