import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import DiagnosisResults from "../components/DiagnosisResults";
import SimulationResults from "../components/SimulationResults";
import type { DiagnoseResponse, RunType, SimulateResponse } from "../types";
import { formatDateTime } from "../utils/format";

export default function RunHistoryPage() {
  const { orgId: orgIdStr } = useParams();
  const orgId = Number(orgIdStr);
  const queryClient = useQueryClient();

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

  const [filter, setFilter] = useState<RunType | "all">("all");
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);

  const runsQuery = useQuery({
    queryKey: ["runs", orgId, filter],
    queryFn: () => api.listRuns(orgId, filter === "all" ? undefined : filter),
  });
  const runs = runsQuery.data ?? [];

  const runDetailQuery = useQuery({
    queryKey: ["run", orgId, selectedRunId],
    queryFn: () => api.getRun(orgId, selectedRunId!),
    enabled: selectedRunId !== null,
  });

  const deleteMutation = useMutation({
    mutationFn: (runId: number) => api.deleteRun(orgId, runId),
    onSuccess: (_data, runId) => {
      queryClient.invalidateQueries({ queryKey: ["runs", orgId] });
      if (selectedRunId === runId) setSelectedRunId(null);
    },
  });

  const detail = runDetailQuery.data;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Run History</h1>
          <p className="page-subtitle">
            {orgQuery.data?.name} — every Simulate and Diagnose run is saved automatically.
            Reopen a past run to see its results again without re-running it.
          </p>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Saved runs</h2>
          <label>
            Type{" "}
            <select value={filter} onChange={(e) => setFilter(e.target.value as RunType | "all")}>
              <option value="all">All</option>
              <option value="simulate">Simulate</option>
              <option value="diagnose">Diagnose</option>
            </select>
          </label>
        </div>
        {runsQuery.isLoading && <p className="muted">Loading...</p>}
        {runs.length === 0 && !runsQuery.isLoading && (
          <p className="muted">No runs yet — go run a Simulate or Diagnose first.</p>
        )}
        {runs.length > 0 && (
          <div className="data-list">
            <div className="data-list-scroll">
              <div
                className="data-list-header"
                style={{ gridTemplateColumns: "170px 100px 1fr 190px" }}
              >
                <div>When</div>
                <div>Type</div>
                <div>Summary</div>
                <div></div>
              </div>
              {runs.map((r) => (
                <div
                  className="data-list-row"
                  key={r.id}
                  style={{ gridTemplateColumns: "170px 100px 1fr 190px" }}
                >
                  <div className="data-list-cell">
                    {formatDateTime(r.created_at)}
                  </div>
                  <div className="data-list-cell">
                    <span className="tag">{r.run_type}</span>
                  </div>
                  <div className="data-list-cell">{r.summary}</div>
                  <div className="data-list-cell actions">
                    <button className="btn" onClick={() => setSelectedRunId(r.id)}>
                      View
                    </button>
                    <button
                      className="btn btn-danger"
                      disabled={deleteMutation.isPending}
                      onClick={() => deleteMutation.mutate(r.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {runDetailQuery.isLoading && <p className="muted">Loading run...</p>}
      {detail && detail.run_type === "simulate" && (
        <SimulationResults result={detail.response as SimulateResponse} />
      )}
      {detail && detail.run_type === "diagnose" && (
        <DiagnosisResults
          diagnosis={detail.response as DiagnoseResponse}
          depts={depts}
          teams={teams}
        />
      )}
    </div>
  );
}
