import type { SimulateResponse } from "../types";
import FanChart from "./FanChart";

const METRICS: { key: string; label: string; color: string }[] = [
  { key: "active_headcount", label: "Active headcount", color: "#6d28d9" },
  { key: "mean_engagement", label: "Mean engagement", color: "#0891b2" },
  { key: "mean_productivity", label: "Mean productivity", color: "#16a34a" },
  { key: "mean_turnover_risk", label: "Mean turnover risk", color: "#dc2626" },
  { key: "mean_burnout", label: "Mean burnout", color: "#ea580c" },
];

export default function SimulationResults({ result }: { result: SimulateResponse }) {
  return (
    <div style={{ marginTop: 24 }}>
      <h2>
        Results — {result.mode === "monte_carlo" ? `${result.replicates} replicates` : "single run"}
      </h2>
      <div className="grid-2">
        {METRICS.map((m) => (
          <div className="card" key={m.key}>
            <FanChart
              rows={result.rows}
              metric={m.key}
              title={m.label}
              color={m.color}
              singleRun={result.mode === "single"}
            />
          </div>
        ))}
      </div>

      <details className="card">
        <summary style={{ cursor: "pointer", fontWeight: 600, color: "var(--text-h)" }}>
          Raw data ({result.rows.length} rows)
        </summary>
        <div className="data-list" style={{ marginTop: 12, maxHeight: 420, overflowY: "auto" }}>
          <div className="data-list-scroll">
            {(() => {
              const cols = `repeat(${result.columns.length}, minmax(96px, 1fr))`;
              return (
                <>
                  <div className="data-list-header" style={{ gridTemplateColumns: cols }}>
                    {result.columns.map((c) => (
                      <div key={c}>{c}</div>
                    ))}
                  </div>
                  {result.rows.map((row, i) => (
                    <div className="data-list-row" key={i} style={{ gridTemplateColumns: cols }}>
                      {result.columns.map((c) => (
                        <div className="data-list-cell" key={c}>
                          {typeof row[c] === "number" ? row[c].toFixed(3) : String(row[c])}
                        </div>
                      ))}
                    </div>
                  ))}
                </>
              );
            })()}
          </div>
        </div>
      </details>
    </div>
  );
}
