import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import { formatDateTime } from "../utils/format";

function EvalTable({ title, evalData }: { title: string; evalData: Record<string, number> | null }) {
  if (!evalData) return <p className="muted">{title}: none</p>;
  return (
    <div>
      <h3>{title}</h3>
      <div className="kv-list">
        {Object.entries(evalData).map(([k, v]) => (
          <div className="kv-row" key={k}>
            <span className="kv-key">{k}</span>
            <span className="kv-value">{typeof v === "number" ? v.toFixed(4) : String(v)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function humanizeFeature(feature: string): string {
  return feature
    .replace(/_/g, " ")
    .replace(/\bpulse mean\b/, "(pulse avg)")
    .replace(/\bpulse trend\b/, "(pulse trend)")
    .replace(/^./, (c) => c.toUpperCase());
}

export default function TrainModelPage() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({ queryKey: ["model-status"], queryFn: api.getModelStatus });
  const qualityQuery = useQuery({ queryKey: ["model-quality"], queryFn: api.getModelQuality });

  const [headcount, setHeadcount] = useState(2000);
  const [replicates, setReplicates] = useState(4);
  const [horizon, setHorizon] = useState(12);
  const [seed, setSeed] = useState(2024);
  const [tolerance, setTolerance] = useState(0.02);
  const [forcePromote, setForcePromote] = useState(false);

  const trainMutation = useMutation({
    mutationFn: () =>
      api.trainModel({ headcount, replicates, horizon, seed, tolerance, force_promote: forcePromote }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["model-status"] });
      queryClient.invalidateQueries({ queryKey: ["model-quality"] });
    },
  });

  const status = statusQuery.data;
  const result = trainMutation.data;
  const quality = qualityQuery.data;
  const history = quality?.history ?? [];
  const qualityChartData = history.map((h) => ({
    date: new Date(h.timestamp).toLocaleDateString("en-US"),
    auc: Math.round((h.candidate_eval.auc ?? 0) * 1000) / 10,
    precisionAt10: Math.round((h.candidate_eval.precision_at_10 ?? 0) * 1000) / 10,
    decision: h.decision,
  }));

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Turnover Model</h1>
          <p className="page-subtitle">
            Retrain the production turnover-risk model used by every org's At-Risk page and
            diagnosis root-cause attribution. Trained on a freshly generated synthetic cohort
            each time, blended with every labeled example collected in the background from real
            Simulate/Diagnose runs across all orgs, then gated against a fixed evaluation
            benchmark before being promoted — the model keeps learning from actual usage without
            ever promoting a regression.
          </p>
        </div>
      </div>

      <div className="card">
        <h2>Current production model</h2>
        {statusQuery.isLoading && <p className="muted">Loading...</p>}
        {status && !status.model_available && (
          <p className="muted">No production model yet — train one below to bootstrap it.</p>
        )}
        {status && status.model_available && (
          <div className="kv-list">
            <div className="kv-row">
              <span className="kv-key">Trained at</span>
              <span className="kv-value">{String(status.metadata.trained_at ?? "-")}</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">Training seed</span>
              <span className="kv-value">{String(status.metadata.training_seed ?? "-")}</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">Training headcount</span>
              <span className="kv-value">{String(status.metadata.training_headcount ?? "-")}</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">Live examples last blended in</span>
              <span className="kv-value">{String(status.metadata.n_live_examples ?? "-")}</span>
            </div>
          </div>
        )}
        {status?.model_available && (
          <EvalTable
            title="Holdout evaluation"
            evalData={(status.metadata.holdout_eval as Record<string, number>) ?? null}
          />
        )}
        {status && (
          <p className="muted" style={{ marginTop: 12 }}>
            <strong>{status.pending_training_examples}</strong> live example
            {status.pending_training_examples === 1 ? "" : "s"} collected from simulation runs across
            all orgs, ready to blend into the next retrain.
          </p>
        )}
      </div>

      <div className="card">
        <h2>Model quality over time</h2>
        <p className="muted">
          Every retrain's holdout AUC and precision@10, in order — a rising or flat line means
          retrains are holding steady or improving; a falling one is exactly what the promotion
          gate exists to catch before it reaches production.
        </p>
        {qualityQuery.isLoading && <p className="muted">Loading...</p>}
        {quality && history.length === 0 && (
          <p className="muted">No retrains recorded yet — train a model below to start the trend.</p>
        )}
        {history.length > 0 && (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={qualityChartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
              <XAxis dataKey="date" fontSize={11} />
              <YAxis fontSize={11} unit="%" domain={[0, 100]} />
              <Tooltip formatter={(v) => `${v}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone" dataKey="auc" name="Holdout AUC" stroke="var(--accent)"
                strokeWidth={2} dot={{ r: 3 }}
              />
              <Line
                type="monotone" dataKey="precisionAt10" name="Precision@10%" stroke="var(--orange)"
                strokeWidth={2} strokeDasharray="4 4" dot={{ r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {quality && quality.feature_importances.length > 0 && (
        <div className="card">
          <h2>Current production model — top drivers</h2>
          <p className="muted" style={{ marginBottom: 12 }}>
            The features the production classifier weighs most heavily when scoring turnover risk.
          </p>
          {quality.feature_importances.map((f, i) => {
            const maxImportance = quality.feature_importances[0].importance || 1;
            return (
              <div className="driver-bar-row" key={f.feature}>
                <div className="driver-bar-labels">
                  <span className="muted">{humanizeFeature(f.feature)}</span>
                  <strong>{(f.importance * 100).toFixed(1)}%</strong>
                </div>
                <div className="risk-bar-track" style={{ width: "100%" }}>
                  <div
                    className="risk-bar-fill"
                    style={{
                      width: `${Math.min(100, (f.importance / maxImportance) * 100)}%`,
                      background: i === 0 ? "var(--accent)" : "#94a3b8",
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {history.length > 0 && (
        <div className="card">
          <h2>Retrain history</h2>
          <div className="data-list">
            <div className="data-list-scroll">
              <div
                className="data-list-header"
                style={{ gridTemplateColumns: "170px 90px 90px 100px 110px 1fr" }}
              >
                <div>When</div>
                <div>Decision</div>
                <div>AUC</div>
                <div>Precision@10</div>
                <div>Live examples</div>
                <div>Reason</div>
              </div>
              {[...history].reverse().map((h, i) => (
                <div
                  className="data-list-row"
                  key={`${h.timestamp}-${i}`}
                  style={{ gridTemplateColumns: "170px 90px 90px 100px 110px 1fr" }}
                >
                  <div className="data-list-cell">{formatDateTime(h.timestamp)}</div>
                  <div className="data-list-cell">
                    <span
                      className="tag"
                      style={{
                        background: h.decision === "PROMOTE" ? "var(--success)" : "var(--danger)",
                        color: "white",
                      }}
                    >
                      {h.decision}
                    </span>
                  </div>
                  <div className="data-list-cell">
                    {typeof h.candidate_eval.auc === "number" ? h.candidate_eval.auc.toFixed(3) : "-"}
                  </div>
                  <div className="data-list-cell">
                    {typeof h.candidate_eval.precision_at_10 === "number"
                      ? `${(h.candidate_eval.precision_at_10 * 100).toFixed(0)}%`
                      : "-"}
                  </div>
                  <div className="data-list-cell">{h.n_live_examples}</div>
                  <div className="data-list-cell">{h.reason}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Retrain</h2>
        <div className="row">
          <label>
            Headcount{" "}
            <input type="number" min={200} max={10000} value={headcount}
              onChange={(e) => setHeadcount(Number(e.target.value))} />
          </label>
          <label>
            Replicates{" "}
            <input type="number" min={1} max={20} value={replicates}
              onChange={(e) => setReplicates(Number(e.target.value))} />
          </label>
          <label>
            Horizon (weeks){" "}
            <input type="number" min={4} max={26} value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))} />
          </label>
          <label>
            Seed{" "}
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
          </label>
          <label>
            Tolerance{" "}
            <input type="number" min={0} max={0.2} step="0.01" value={tolerance}
              onChange={(e) => setTolerance(Number(e.target.value))} />
          </label>
          <label>
            <input type="checkbox" checked={forcePromote}
              onChange={(e) => setForcePromote(e.target.checked)} />{" "}
            Force promote
          </label>
        </div>
        <button
          className="btn btn-primary"
          style={{ marginTop: 10 }}
          disabled={trainMutation.isPending}
          onClick={() => trainMutation.mutate()}
        >
          {trainMutation.isPending ? "Training (this can take a while)..." : "Train candidate model"}
        </button>
        {trainMutation.isError && (
          <p className="error">{(trainMutation.error as Error).message}</p>
        )}

        {result && (
          <div style={{ marginTop: 16 }}>
            <p>
              <span
                className="tag"
                style={{
                  background: result.decision === "PROMOTE" ? "var(--success)" : "var(--danger)",
                  color: "white",
                }}
              >
                {result.decision}
              </span>{" "}
              {result.reason}
            </p>
            <p className="muted">
              Blended {result.n_live_examples} live example{result.n_live_examples === 1 ? "" : "s"} from
              simulation runs into this retrain.
            </p>
            <div className="grid-2">
              <EvalTable title="Candidate (this run)" evalData={result.candidate_eval} />
              <EvalTable title="Production (previous)" evalData={result.production_eval} />
            </div>
            <EvalTable title="Train-split report" evalData={result.train_report} />
          </div>
        )}
      </div>
    </div>
  );
}
