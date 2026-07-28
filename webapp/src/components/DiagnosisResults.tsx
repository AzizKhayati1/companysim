import type { DepartmentOut, DiagnoseResponse, DiagnosisReportOut, TeamOut } from "../types";

interface Props {
  diagnosis: DiagnoseResponse;
  depts: DepartmentOut[];
  teams: TeamOut[];
  onApplyRecommendation?: (report: DiagnosisReportOut) => void;
}

export default function DiagnosisResults({ diagnosis, depts, teams, onApplyRecommendation }: Props) {
  const deptName = (id: number | null) => depts.find((d) => d.id === id)?.name ?? `dept ${id}`;
  const teamName = (id: number | null) => teams.find((t) => t.id === id)?.name ?? `team ${id}`;
  const segmentLabel = (segmentType: string, segmentId: string) => {
    const id = Number(segmentId);
    return segmentType === "department" ? deptName(id) : teamName(id);
  };

  return (
    <div style={{ marginTop: 24 }}>
      <h2>Diagnosis — {diagnosis.problems_detected} problem(s) detected</h2>
      {!diagnosis.model_available && (
        <p className="muted">
          No trained turnover model found — drivers are equally weighted rather than
          ranked by the model's learned feature importance. Run{" "}
          <code>scripts/train_turnover_model.py</code> for weighted attribution.
        </p>
      )}
      {diagnosis.reports.length === 0 && (
        <p className="muted">No threshold crossings detected in this run — looks stable.</p>
      )}
      {diagnosis.reports.map((report, i) => (
        <div className="card" key={i}>
          <h3>{report.problem.metric} @ week {report.problem.tick}</h3>
          <p>{report.problem.description}</p>
          {report.drivers.length > 0 && (
            <>
              <p className="muted">Top contributing factors:</p>
              <ul>
                {report.drivers.map((d, j) => (
                  <li key={j}>
                    <strong>{segmentLabel(d.segment_type, d.segment_id)}</strong> ({d.segment_type}) —{" "}
                    {d.feature}: {d.segment_mean.toFixed(2)} vs org avg {d.org_mean.toFixed(2)}{" "}
                    ({d.deviation >= 0 ? "+" : ""}{d.deviation.toFixed(2)})
                  </li>
                ))}
              </ul>
            </>
          )}
          <p>{report.explanation}</p>
          {report.notes_summary && report.notes_summary.sample_quotes.length > 0 && (
            <div
              className="muted"
              style={{
                borderLeft: "3px solid var(--accent)",
                background: "var(--accent-bg)",
                borderRadius: "0 8px 8px 0",
                padding: "8px 14px",
                marginBottom: 12,
              }}
            >
              {report.notes_summary.sample_quotes.map((q, k) => (
                <p key={k} style={{ fontStyle: "italic", margin: "4px 0" }}>&ldquo;{q}&rdquo;</p>
              ))}
              {report.notes_summary.n_llm_generated > 0 && (
                <p style={{ margin: "4px 0", fontSize: 12 }}>
                  {report.notes_summary.n_llm_generated} of {report.notes_summary.n_notes} note(s)
                  above were AI-generated, grounded in this employee's own risk-driver
                  values.
                </p>
              )}
            </div>
          )}
          <div className="row">
            <span className="tag">{report.recommendation.event_type.replace(/_/g, " ")}</span>
            {onApplyRecommendation && (
              <button className="btn" onClick={() => onApplyRecommendation(report)}>
                + Add recommended event to scenario
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
