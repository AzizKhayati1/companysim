import type { LineageTargetOut } from "../types";

/**
 * Provenance flow: document → extracted column/value → the table row it
 * lands in → what that feeds downstream.
 *
 * Deliberately NOT colour-coded by destination table. The app's four
 * non-neutral tokens fail as a categorical palette — accent (#00867a) vs
 * success (#1f9d55) is ΔE 10.1 in normal vision, below the readable
 * floor, and warning vs success is ΔE 4.8 under protanopia — so hue here
 * would encode identity that a reader cannot actually decode. Table
 * identity is carried by its monospaced name instead.
 *
 * Colour is reserved for *state*, and always ships with an icon and a
 * word, never on its own. `--warning` is 2.83:1 on white, so state is a
 * tinted chip with regular ink rather than coloured text.
 */

type State = LineageTargetOut["state"];

const STATE_META: Record<State, { label: string; bg: string; fg: string; icon: string }> = {
  written: { label: "Written", bg: "var(--success-bg)", fg: "var(--success)", icon: "M4 8.5 L7 11.5 L12.5 5" },
  applied: { label: "Applied", bg: "var(--success-bg)", fg: "var(--success)", icon: "M4 8.5 L7 11.5 L12.5 5" },
  pending: { label: "Awaiting approval", bg: "var(--warning-bg)", fg: "var(--warning)", icon: "M8 4 V8.5 L11 10.5" },
};

function StateChip({ state }: { state: State }) {
  const meta = STATE_META[state];
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        background: meta.bg, borderRadius: 999, padding: "2px 9px",
        fontSize: 12, fontWeight: 600, color: "var(--text-h)", whiteSpace: "nowrap",
      }}
    >
      <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true">
        {state === "pending" && (
          <circle cx="8" cy="8" r="6" fill="none" stroke={meta.fg} strokeWidth="1.6" />
        )}
        <path
          d={meta.icon} fill="none" stroke={meta.fg} strokeWidth="1.9"
          strokeLinecap="round" strokeLinejoin="round"
        />
      </svg>
      {meta.label}
    </span>
  );
}

function Arrow() {
  return (
    <svg width="20" height="12" viewBox="0 0 20 12" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path
        d="M1 6 H16 M12.5 2.5 L16 6 L12.5 9.5"
        fill="none" stroke="var(--border-strong)" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  );
}

const mono = { fontFamily: "var(--mono)", fontSize: 12.5 } as const;

export default function ExtractionLineage({
  targets,
  downstream,
  filename,
}: {
  targets: LineageTargetOut[];
  downstream: string[];
  filename: string;
}) {
  if (targets.length === 0) {
    return (
      <p className="muted">
        This document has not written anything to the database. Nothing was extracted from it,
        so there is no provenance to show — that is the honest empty state, not a loading one.
      </p>
    );
  }

  return (
    <div>
      <div
        style={{
          display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
          marginBottom: 14, paddingBottom: 12, borderBottom: "1px solid var(--border)",
        }}
      >
        <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true">
          <path
            d="M4 2.5 h7 l5 5 v10 a1 1 0 0 1 -1 1 h-11 a1 1 0 0 1 -1 -1 v-14 a1 1 0 0 1 1 -1 z"
            fill="none" stroke="var(--text-3)" strokeWidth="1.5" strokeLinejoin="round"
          />
          <path d="M11 2.5 V7.5 h5" fill="none" stroke="var(--text-3)" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
        <span style={{ ...mono, color: "var(--text-h)" }}>{filename}</span>
        <Arrow />
        <span className="muted" style={{ fontSize: 13 }}>
          writes to {targets.length} destination{targets.length === 1 ? "" : "s"}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {targets.map((t, i) => (
          <div
            key={`${t.table}-${t.row_id ?? t.employee_id ?? i}-${t.state}`}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                padding: "9px 12px", background: "var(--surface-2)",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span style={{ ...mono, color: "var(--text-h)", fontWeight: 600 }}>{t.table}</span>
              {t.row_id !== null && (
                <span className="muted" style={{ ...mono }}>id={t.row_id}</span>
              )}
              {t.employee_name && (
                <span className="muted" style={{ fontSize: 13 }}>
                  {t.employee_name}
                  {t.employee_id !== null && (
                    <span style={{ ...mono }}> (#{t.employee_id})</span>
                  )}
                </span>
              )}
              <span style={{ marginLeft: "auto" }}>
                <StateChip state={t.state} />
              </span>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 520 }}>
                <thead>
                  <tr>
                    {["Column", "Extracted value", "Feeds"].map((h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: "left", padding: "7px 12px", fontSize: 11,
                          letterSpacing: "0.04em", textTransform: "uppercase",
                          color: "var(--text-3)", fontWeight: 600,
                          borderBottom: "1px solid var(--border)", whiteSpace: "nowrap",
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {t.fields.map((f) => (
                    <tr key={f.column}>
                      <td style={{ padding: "8px 12px", verticalAlign: "top", ...mono, color: "var(--text-h)" }}>
                        {f.column}
                      </td>
                      <td
                        style={{
                          padding: "8px 12px", verticalAlign: "top",
                          color: "var(--text-h)", maxWidth: 320,
                        }}
                      >
                        {f.value}
                      </td>
                      <td
                        className="muted"
                        style={{ padding: "8px 12px", verticalAlign: "top", fontSize: 12.5 }}
                      >
                        {f.note || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>

      {downstream.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div
            style={{
              fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase",
              color: "var(--text-3)", fontWeight: 600, marginBottom: 8,
            }}
          >
            Downstream effect
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
            {downstream.map((d) => (
              <li key={d} className="muted" style={{ fontSize: 13 }}>{d}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
