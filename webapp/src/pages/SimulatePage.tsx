import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import DiagnosisResults from "../components/DiagnosisResults";
import SimulationResults from "../components/SimulationResults";
import {
  LEVELS,
  LIFE_EVENT_TYPES,
  type DiagnosisReportOut,
  type ScenarioEventIn,
  type ScenarioEventType,
} from "../types";

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

export default function SimulatePage() {
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
  const empsQuery = useQuery({
    queryKey: ["employees", orgId],
    queryFn: () => api.listEmployees(orgId),
  });
  const depts = deptsQuery.data ?? [];
  const teams = teamsQuery.data ?? [];
  const emps = empsQuery.data ?? [];

  const [ticks, setTicks] = useState(12);
  const [replicates, setReplicates] = useState(1);
  const [seed, setSeed] = useState(1234);
  const [events, setEvents] = useState<ScenarioEventIn[]>([]);

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
  const diagnoseMutation = useMutation({
    mutationFn: () => api.diagnose(orgId, { ticks, replicates: 1, seed, events }),
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

  const result = simulateMutation.data;
  const diagnosis = diagnoseMutation.data;

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 16 }}>
        <Link to="/">&larr; All orgs</Link>
        <Link to={`/orgs/${orgId}`}>&larr; Edit org</Link>
        <Link to={`/orgs/${orgId}/at-risk`}>At-Risk employees &rarr;</Link>
        <Link to={`/orgs/${orgId}/runs`}>Run history &rarr;</Link>
      </div>
      <h1>Simulate — {orgQuery.data?.name}</h1>

      <div className="card">
        <h2>Run settings</h2>
        <div className="row">
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
      </div>

      <div className="card">
        <h2>Scenario events</h2>
        <p className="muted">
          Global levers affect a department or the whole org; targeted levers hit named
          employees; life events model things happening outside work.
        </p>
        {events.length > 0 && (
          <div className="data-list" style={{ marginBottom: 12 }}>
            <div className="data-list-scroll">
              <div className="data-list-header" style={{ gridTemplateColumns: "60px 150px 1fr 46px" }}>
                <div>Tick</div>
                <div>Type</div>
                <div>Params</div>
                <div></div>
              </div>
              {events.map((e, i) => (
                <div
                  className="data-list-row"
                  key={i}
                  style={{ gridTemplateColumns: "60px 150px 1fr 46px" }}
                >
                  <div className="data-list-cell">{e.at_tick}</div>
                  <div className="data-list-cell">{e.type}</div>
                  <div className="data-list-cell">
                    <code>{JSON.stringify(e.params)}</code>
                  </div>
                  <div className="data-list-cell actions">
                    <button
                      className="btn btn-danger"
                      onClick={() => setEvents(events.filter((_, j) => j !== i))}
                    >
                      &times;
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

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
      </div>

      <div className="row">
        <button
          className="btn btn-primary"
          disabled={simulateMutation.isPending}
          onClick={() => simulateMutation.mutate()}
        >
          {simulateMutation.isPending ? "Running..." : "Run simulation"}
        </button>
        <button
          className="btn"
          disabled={diagnoseMutation.isPending}
          onClick={() => diagnoseMutation.mutate()}
        >
          {diagnoseMutation.isPending ? "Diagnosing..." : "Diagnose"}
        </button>
        <button
          className="btn"
          disabled={exportPdfMutation.isPending}
          onClick={() => exportPdfMutation.mutate()}
        >
          {exportPdfMutation.isPending ? "Exporting..." : "Export PDF"}
        </button>
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

      {diagnosis && (
        <DiagnosisResults
          diagnosis={diagnosis}
          depts={depts}
          teams={teams}
          onApplyRecommendation={applyRecommendation}
        />
      )}

      {result && <SimulationResults result={result} />}
    </div>
  );
}
