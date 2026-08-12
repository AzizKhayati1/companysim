import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { DOCUMENT_KINDS } from "../types";
import type { DocumentKind, ExtractedFactOut } from "../types";
import { formatDateTime } from "../utils/format";
import ExtractionLineage from "../components/ExtractionLineage";

const KIND_LABELS: Record<string, string> = {
  roster: "Roster export",
  offer_letter: "Offer letter (hiring)",
  cv: "CV / résumé",
  performance_review: "Performance review",
  resignation_letter: "Resignation letter",
  pulse_export: "Pulse survey export",
};

const KIND_HINTS: Record<DocumentKind, string> = {
  roster: "CSV with an email column. Parsed deterministically — no API key needed.",
  offer_letter:
    "Hires someone new. Must name a department — an employee has to be placed somewhere. "
    + "Staged as a new-hire proposal; approving it creates the employee.",
  cv: "Proposes a candidate. A CV usually doesn't state a department or salary — those are "
    + "the offer's job — so approving one is normally refused until an offer letter follows.",
  performance_review: "Free text or PDF. Needs the LLM extractor configured.",
  resignation_letter: "Free text or PDF. Needs the LLM extractor configured.",
  pulse_export: "Not parsed yet — uploads are stored and parked for review.",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Not extracted",
  extracted: "Extracted",
  needs_review: "Needs review",
};

function statusColor(status: string): string {
  if (status === "extracted") return "var(--success)";
  if (status === "needs_review") return "var(--warning)";
  return "var(--text-3)";
}

const FIELD_LABELS: Record<string, string> = {
  full_name: "Name",
  level: "Level",
  role: "Role",
  tenure_months: "Tenure (months)",
  base_salary: "Base salary",
  promotions_count: "Promotions",
  department_name: "Department",
  team_name: "Team",
  new_hire: "New hire",
};

export default function DocumentsPage() {
  const { orgId: orgIdStr } = useParams();
  const orgId = Number(orgIdStr);
  const queryClient = useQueryClient();

  const [kind, setKind] = useState<DocumentKind>("roster");
  const [asOfDate, setAsOfDate] = useState("");
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [approved, setApproved] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const orgQuery = useQuery({ queryKey: ["org", orgId], queryFn: () => api.getOrg(orgId) });
  const docsQuery = useQuery({
    queryKey: ["documents", orgId],
    queryFn: () => api.listDocuments(orgId),
  });
  const totalsQuery = useQuery({
    queryKey: ["ingest-totals", orgId],
    queryFn: () => api.getIngestTotals(orgId),
  });
  const cohortQuery = useQuery({
    queryKey: ["document-cohort", orgId],
    queryFn: () => api.getDocumentCohort(orgId),
  });
  const detailQuery = useQuery({
    queryKey: ["document", orgId, selectedDocId],
    queryFn: () => api.getDocument(orgId, selectedDocId!),
    enabled: selectedDocId !== null,
  });
  const lineageQuery = useQuery({
    queryKey: ["document-lineage", orgId, selectedDocId],
    queryFn: () => api.getDocumentLineage(orgId, selectedDocId!),
    enabled: selectedDocId !== null,
  });
  // Not org-scoped and not invalidated by refreshAll: this describes the
  // server's environment, which no action on this page can change. It is
  // the live counterpart to each document's stored extraction_error.
  const llmStatusQuery = useQuery({
    queryKey: ["llm-status"],
    queryFn: () => api.getLlmStatus(),
    staleTime: 30_000,
  });
  const llmStatus = llmStatusQuery.data;

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["documents", orgId] });
    queryClient.invalidateQueries({ queryKey: ["ingest-totals", orgId] });
    queryClient.invalidateQueries({ queryKey: ["document-cohort", orgId] });
    queryClient.invalidateQueries({ queryKey: ["document", orgId] });
    queryClient.invalidateQueries({ queryKey: ["document-lineage", orgId] });
    queryClient.invalidateQueries({ queryKey: ["employees", orgId] });
  };

  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadDocument(orgId, file, kind, asOfDate || undefined),
    onSuccess: (doc) => {
      setError(null);
      setNotice(`Uploaded ${doc.filename}. Run Extract to stage its changes.`);
      if (fileRef.current) fileRef.current.value = "";
      refreshAll();
    },
    onError: (e: Error) => { setNotice(null); setError(e.message); },
  });

  const extractMutation = useMutation({
    mutationFn: (documentId: number) => api.extractDocument(orgId, documentId),
    onSuccess: (res) => {
      setError(null);
      setApproved(new Set());
      setSelectedDocId(res.document.id);
      // Only rosters stage reviewable facts. A performance review or
      // resignation letter writes its record directly (there is no
      // per-field diff to approve), so "0 facts staged" means success for
      // those and "no differences" for a roster — saying the latter for a
      // letter would report a successful ingest as a no-op.
      const stagesFacts = res.document.kind === "roster";
      setNotice(
        res.n_facts_staged > 0
          ? `Staged ${res.n_facts_staged} proposed change${res.n_facts_staged === 1 ? "" : "s"} for review.`
          : res.document.extraction_status === "needs_review"
            ? "Nothing was extracted — see the reason below. No data was changed."
            : stagesFacts
              ? "Extraction found no differences from the current org."
              : "Extracted. Re-running Extract replaces this document's record rather than adding a second one.",
      );
      refreshAll();
    },
    onError: (e: Error) => { setNotice(null); setError(e.message); },
  });

  const applyMutation = useMutation({
    mutationFn: (documentId: number) =>
      api.applyDocumentFacts(orgId, documentId, [...approved]),
    onSuccess: (res) => {
      setError(null);
      setApproved(new Set());
      const bits = [`${res.n_applied} applied`, `${res.n_rejected} rejected`];
      if (res.n_employees_created > 0) bits.push(`${res.n_employees_created} employee(s) created`);
      setNotice(bits.join(" · "));
      if (res.unapplied.length > 0) setError(res.unapplied.join("\n"));
      refreshAll();
    },
    onError: (e: Error) => { setNotice(null); setError(e.message); },
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: number) => api.deleteDocument(orgId, documentId),
    onSuccess: () => {
      setSelectedDocId(null);
      setApproved(new Set());
      setNotice("Document deleted. Any changes already applied to employees stay applied.");
      refreshAll();
    },
    onError: (e: Error) => { setNotice(null); setError(e.message); },
  });

  const documents = docsQuery.data ?? [];
  const totals = totalsQuery.data;
  const cohort = cohortQuery.data;
  const detail = detailQuery.data;
  const facts = detail?.pending_facts ?? [];

  const toggleFact = (id: number) => {
    setApproved((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const factLabel = (f: ExtractedFactOut) => FIELD_LABELS[f.field_name] ?? f.field_name;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Document Ingestion</h1>
          <p className="page-subtitle">
            {orgQuery.data?.name} — upload real HR documents to enrich this org. Every proposed
            change is staged for your review with the source text it came from; nothing is written
            to an employee record until you approve it.
          </p>
        </div>
      </div>

      {notice && <div className="card" style={{ borderLeft: "3px solid var(--accent)" }}>{notice}</div>}
      {error && (
        <div className="card" style={{ borderLeft: "3px solid var(--danger)", whiteSpace: "pre-wrap" }}>
          {error}
        </div>
      )}

      {totals && (
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-label">Documents</div>
            <div className="stat-value">{totals.n_documents}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Awaiting review</div>
            <div className="stat-value">{totals.n_pending_facts}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Performance reviews</div>
            <div className="stat-value">{totals.n_performance_reviews}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Ingested exit notes</div>
            <div className="stat-value">{totals.n_ingested_exit_notes}</div>
          </div>
        </div>
      )}

      {/* Free-text extraction fails silently by design — a document parks
          itself as "needs review" whether the model declined or the server
          was never configured. Those look identical per-document, so the
          server's live state is stated once, here, where it is read before
          uploading rather than discovered afterwards. Rosters are excluded
          from the warning: they parse deterministically and never need a
          provider at all. */}
      {llmStatus && !llmStatus.features?.ingest && (
        <div className="card" style={{ borderLeft: "3px solid var(--warning)" }}>
          <strong>Free-text extraction is off.</strong>{" "}
          {llmStatus.provider_problem ?? "COMPANYSIM_LLM_INGEST=1 is not set."}
          <p className="muted" style={{ margin: "8px 0 0" }}>
            Roster CSVs still parse normally — they never call a model. Everything
            else will upload and park as <em>needs review</em>. The server reads
            its configuration once at startup, so restart it after editing{" "}
            <code>.env</code>.
          </p>
        </div>
      )}

      <div className="card">
        <h2>Upload a document</h2>
        <p className="muted" style={{ marginBottom: 12 }}>{KIND_HINTS[kind]}</p>
        <div className="row" style={{ flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
          <label>
            Type
            <select value={kind} onChange={(e) => setKind(e.target.value as DocumentKind)}>
              {DOCUMENT_KINDS.map((k) => (
                <option key={k} value={k}>{KIND_LABELS[k] ?? k}</option>
              ))}
            </select>
          </label>
          <label>
            As-of date
            <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
          </label>
          <label>
            File
            <input ref={fileRef} type="file" accept=".csv,.txt,.md,.pdf" />
          </label>
          <button
            className="btn btn-primary"
            disabled={uploadMutation.isPending}
            onClick={() => {
              const file = fileRef.current?.files?.[0];
              if (!file) { setError("Choose a file first."); return; }
              uploadMutation.mutate(file);
            }}
          >
            {uploadMutation.isPending ? "Uploading..." : "Upload"}
          </button>
        </div>
        <p className="muted" style={{ marginTop: 10 }}>
          The as-of date is the date the document's facts are true as of. For a roster it defines
          the training window's start; it is what stops a document written after an outcome from
          being used to predict it.
        </p>
      </div>

      <div className="card">
        <h2>Documents</h2>
        {docsQuery.isLoading && <p className="muted">Loading...</p>}
        {!docsQuery.isLoading && documents.length === 0 && (
          <p className="muted">No documents uploaded yet.</p>
        )}
        {documents.length > 0 && (
          <div className="data-list">
            <div className="data-list-scroll">
              <div
                className="data-list-header"
                style={{ gridTemplateColumns: "1fr 150px 120px 130px 190px" }}
              >
                <div>File</div>
                <div>Type</div>
                <div>As of</div>
                <div>Status</div>
                <div>Actions</div>
              </div>
              {documents.map((d) => (
                <div
                  key={d.id}
                  className={`data-list-row${selectedDocId === d.id ? " active" : ""}`}
                  style={{ gridTemplateColumns: "1fr 150px 120px 130px 190px" }}
                >
                  <div>
                    <strong>{d.filename}</strong>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {formatDateTime(d.uploaded_at)}
                    </div>
                  </div>
                  <div className="muted">{KIND_LABELS[d.kind] ?? d.kind}</div>
                  <div className="muted">{d.as_of_date ?? "—"}</div>
                  <div style={{ color: statusColor(d.extraction_status) }}>
                    {STATUS_LABELS[d.extraction_status] ?? d.extraction_status}
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      className="btn"
                      disabled={extractMutation.isPending}
                      onClick={() => extractMutation.mutate(d.id)}
                    >
                      Extract
                    </button>
                    <button
                      className="btn"
                      onClick={() => { setSelectedDocId(d.id); setApproved(new Set()); }}
                    >
                      Review
                    </button>
                    <button
                      className="btn btn-danger"
                      onClick={() => deleteMutation.mutate(d.id)}
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

      {detail && (
        <div className="card">
          <h2>Review — {detail.filename}</h2>
          {detail.extraction_error && (
            <>
              <p className="muted" style={{ marginBottom: 12 }}>
                <strong>Not extracted:</strong> {detail.extraction_error}
              </p>
              {/* The reason above is a *stored* string, written when Extract
                  last ran — not a live check. Fixing the configuration does
                  not rewrite it, so after a provider change the panel keeps
                  reporting a problem that no longer exists. Saying so, and
                  only when the server is now ready, turns a confusing
                  contradiction into an obvious next step. */}
              {llmStatus?.features?.ingest && (
                <p
                  className="muted"
                  style={{ marginBottom: 12, borderLeft: "2px solid var(--accent)", paddingLeft: 10 }}
                >
                  That reason is from the last extraction attempt. Extraction is
                  working now ({llmStatus.provider} · {llmStatus.model}) — run{" "}
                  <strong>Extract</strong> again to retry this document.
                </p>
              )}
            </>
          )}
          {facts.length === 0 && !detail.extraction_error && (
            <p className="muted">
              Nothing awaiting review for this document. Run Extract, or everything staged has
              already been decided.
            </p>
          )}
          {facts.length > 0 && (
            <>
              <p className="muted" style={{ marginBottom: 12 }}>
                Tick the changes you want applied. Anything left unticked is rejected — a change
                is never applied by default.
              </p>
              <div className="data-list">
                <div className="data-list-scroll">
                  <div
                    className="data-list-header"
                    style={{ gridTemplateColumns: "44px 90px 150px 1fr 1fr" }}
                  >
                    <div>
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={approved.size === facts.length && facts.length > 0}
                        onChange={(e) =>
                          setApproved(e.target.checked ? new Set(facts.map((f) => f.id)) : new Set())
                        }
                      />
                    </div>
                    <div>Employee</div>
                    <div>Field</div>
                    <div>Change</div>
                    <div>Evidence</div>
                  </div>
                  {facts.map((f) => (
                    <div
                      key={f.id}
                      className="data-list-row"
                      style={{ gridTemplateColumns: "44px 90px 150px 1fr 1fr" }}
                    >
                      <div>
                        <input
                          type="checkbox"
                          aria-label={`Approve change ${f.id}`}
                          checked={approved.has(f.id)}
                          onChange={() => toggleFact(f.id)}
                        />
                      </div>
                      <div className="muted">
                        {f.target_employee_id ?? <em>new</em>}
                      </div>
                      <div>{factLabel(f)}</div>
                      <div>
                        {f.field_name === "new_hire" ? (
                          <span className="muted">Not currently in this org — will be created</span>
                        ) : (
                          <>
                            <span className="muted">{f.current_value ?? "—"}</span>
                            {" → "}
                            <strong>{f.proposed_value}</strong>
                          </>
                        )}
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>{f.evidence_span}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
                <button
                  className="btn btn-primary"
                  disabled={approved.size === 0 || applyMutation.isPending}
                  onClick={() => applyMutation.mutate(detail.id)}
                >
                  {applyMutation.isPending
                    ? "Applying..."
                    : `Apply ${approved.size} selected`}
                </button>
                <span className="muted">
                  {facts.length - approved.size} will be rejected
                </span>
              </div>
            </>
          )}
        </div>
      )}

      {detail && lineageQuery.data && (
        <div className="card">
          <h2>Where this lands</h2>
          <p className="muted" style={{ marginBottom: 14 }}>
            Every row this document wrote or proposes to write, read back from the database
            itself — not re-derived from the file, so a document that extracted nothing shows
            nothing.
          </p>
          <ExtractionLineage
            filename={detail.filename}
            targets={lineageQuery.data.targets}
            downstream={lineageQuery.data.downstream}
          />
          {lineageQuery.data.extractor && (
            <p className="muted" style={{ marginTop: 14, fontSize: 12.5 }}>
              Extracted by <code>{lineageQuery.data.extractor}</code>
            </p>
          )}
        </div>
      )}

      <div className="card">
        <h2>Training cohort</h2>
        {cohort?.usable === false && (
          <>
            <p className="muted">{cohort.reason}</p>
            <p className="muted" style={{ marginTop: 10 }}>
              You only ever receive a resignation letter from someone who left, so letters alone
              are a 100%-positive sample. A roster is what supplies the denominator — everyone on
              it who <em>didn't</em> leave becomes a labeled negative. Without one, these documents
              contribute nothing to <Link to="/model">model training</Link>, deliberately.
            </p>
          </>
        )}
        {cohort?.usable && (
          <>
            <div className="stat-grid">
              <div className="stat-card">
                <div className="stat-label">Left (positives)</div>
                <div className="stat-value">{cohort.n_positives}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Stayed (negatives)</div>
                <div className="stat-value">{cohort.n_negatives}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Base rate</div>
                <div className="stat-value">{(cohort.base_rate * 100).toFixed(1)}%</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Unmatched letters</div>
                <div className="stat-value">{cohort.n_unmatched_resignations}</div>
              </div>
            </div>
            <p className="muted" style={{ marginTop: 12 }}>
              Outcome window {cohort.window_start} → {cohort.window_end}. These labeled examples
              are blended into the next retrain on the{" "}
              <Link to="/model">Turnover Model</Link> page, still judged against the same fixed
              synthetic benchmark — real data can only help or be a no-op, never silently degrade
              production.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
