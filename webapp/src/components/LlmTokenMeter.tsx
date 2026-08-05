import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatDateTime } from "../utils/format";

/**
 * Top-right token meter for every Groq-backed feature.
 *
 * Numbers only — no chart. There are three windows and a handful of
 * per-feature rows; a bar chart of four categories would be decoration
 * over a table that reads faster. The headline (today's spend) is a hero
 * number, which is the right form when a single value *is* the answer.
 *
 * No colour encodes magnitude: "a lot of tokens" has no threshold in this
 * app (no quota is configured), so tinting a number red would assert a
 * judgement the data doesn't support. Colour is used only for the live/idle
 * dot, and it ships with a word beside it.
 */

const FEATURE_LABELS: Record<string, string> = {
  chat: "Ask Vantage",
  exit_notes: "Exit notes",
  ingest: "Document ingestion",
};

function compact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

const full = (n: number) => n.toLocaleString("en-US");

function Row({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16 }}>
      <span className="muted" style={{ fontSize: 12.5 }}>{label}</span>
      <span style={{ fontSize: 13, color: "var(--text-h)", fontVariantNumeric: "tabular-nums" }}>
        {value}
        {sub && <span className="muted" style={{ fontSize: 11.5, marginLeft: 6 }}>{sub}</span>}
      </span>
    </div>
  );
}

export default function LlmTokenMeter() {
  const [open, setOpen] = useState(false);
  const { data, isError } = useQuery({
    queryKey: ["llm-usage"],
    queryFn: () => api.getLlmUsage(),
    // Cheap aggregate query; refresh often enough that a chat reply or a
    // document extraction visibly moves the number without a page reload.
    refetchInterval: 10_000,
  });

  if (isError) return null;

  const today = data?.today.total_tokens ?? 0;
  const requestsToday = data?.today.requests ?? 0;
  const lastRequest = data?.recent[0];

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label="LLM token usage"
        style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 999, padding: "6px 13px", cursor: "pointer",
          boxShadow: "var(--shadow-xs)", color: "var(--text-h)",
          font: "inherit", fontSize: 13,
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
          <path
            d="M8 1.5 L14 5 v6 L8 14.5 L2 11 V5 Z"
            fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round"
          />
          <circle cx="8" cy="8" r="2.1" fill="var(--accent)" />
        </svg>
        <span style={{ fontVariantNumeric: "tabular-nums" }}>{compact(today)}</span>
        <span className="muted" style={{ fontSize: 12 }}>tokens today</span>
      </button>

      {open && (
        <>
          {/* Click-away layer, behind the panel but above the page. */}
          <div
            onClick={() => setOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 40 }}
            aria-hidden="true"
          />
          <div
            style={{
              position: "absolute", top: "calc(100% + 8px)", right: 0, zIndex: 41,
              width: 340, maxWidth: "calc(100vw - 32px)",
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: "var(--radius-lg)", boxShadow: "var(--shadow-md)",
              padding: 16,
            }}
          >
            <div style={{ marginBottom: 14 }}>
              <div className="muted" style={{ fontSize: 12 }}>Tokens today (UTC)</div>
              <div
                style={{
                  fontSize: 30, fontWeight: 650, color: "var(--text-h)",
                  lineHeight: 1.15, fontVariantNumeric: "tabular-nums",
                }}
              >
                {full(today)}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                across {requestsToday} request{requestsToday === 1 ? "" : "s"}
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: 14 }}>
              <Row
                label="Last 7 days"
                value={full(data?.week.total_tokens ?? 0)}
                sub={`${data?.week.requests ?? 0} req`}
              />
              <Row
                label="All time"
                value={full(data?.all_time.total_tokens ?? 0)}
                sub={`${data?.all_time.requests ?? 0} req`}
              />
              <Row
                label="Prompt / completion (all time)"
                value={`${compact(data?.all_time.prompt_tokens ?? 0)} / ${compact(data?.all_time.completion_tokens ?? 0)}`}
              />
            </div>

            {(data?.by_feature.length ?? 0) > 0 && (
              <>
                <div
                  style={{
                    fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase",
                    color: "var(--text-3)", fontWeight: 600, marginBottom: 7,
                  }}
                >
                  By feature
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
                  {data!.by_feature.map((f) => (
                    <Row
                      key={f.feature}
                      label={FEATURE_LABELS[f.feature] ?? f.feature}
                      value={full(f.total_tokens)}
                      sub={`${f.requests} req`}
                    />
                  ))}
                </div>
              </>
            )}

            <div
              style={{
                fontSize: 11, letterSpacing: "0.04em", textTransform: "uppercase",
                color: "var(--text-3)", fontWeight: 600, marginBottom: 7,
              }}
            >
              Last request
            </div>
            {lastRequest ? (
              <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                <div style={{ color: "var(--text-h)" }}>
                  {FEATURE_LABELS[lastRequest.feature] ?? lastRequest.feature}
                  {" · "}
                  <span style={{ fontVariantNumeric: "tabular-nums" }}>
                    {full(lastRequest.total_tokens)} tokens
                  </span>
                </div>
                <div>
                  {full(lastRequest.prompt_tokens)} in / {full(lastRequest.completion_tokens)} out
                </div>
                <div>{formatDateTime(lastRequest.created_at)}</div>
                <div style={{ fontFamily: "var(--mono)", fontSize: 11.5 }}>{lastRequest.model}</div>
              </div>
            ) : (
              <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>
                No LLM requests recorded yet. The optional Groq features are off by default —
                see the README for the flags.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
