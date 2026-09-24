import { useEffect, useRef, useState } from "react";
import { uploadFiling, fetchFiling, getFilingJob, ApiError } from "../../lib/api";
import { CloseIcon, PlusIcon, UploadIcon } from "../../components/ui/icons";

const POLL_MS = 1500;

const inputClass =
  "w-full text-[13.5px] rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2.5 text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)] outline-none focus:border-[var(--color-brand)] transition-colors disabled:opacity-60";

function ModeTab({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 text-[13px] font-medium px-3 py-1.5 rounded-[5px] transition-colors cursor-pointer ${
        active ? "bg-[var(--color-surface)] text-[var(--color-ink)] shadow-sm" : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
      }`}
    >
      {children}
    </button>
  );
}

function IngestProgress({ job, progressPct }) {
  if (job.status === "error") {
    return (
      <p className="rounded-[var(--radius-sm)] bg-[var(--color-error-tint)] px-3 py-2.5 text-[13px] text-[var(--color-ink)]">
        {job.error || "We couldn't add this annual report."}
      </p>
    );
  }
  const done = job.status === "done";
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 py-3">
      <div className="flex items-center justify-between gap-3 mb-2">
        <span className="text-[13px] text-[var(--color-ink)]">{done ? "Annual report added" : job.detail || "Indexing the report…"}</span>
        <span className="tnum text-[12px] text-[var(--color-ink-faint)]">
          {done ? `${job.chunks} passages` : job.chunks_total ? `${job.chunks_done}/${job.chunks_total}` : ""}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--color-surface-sunken)] overflow-hidden">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${done ? 100 : progressPct}%`, background: done ? "var(--color-ok)" : "var(--color-running)" }}
        />
      </div>
      {done && <p className="mt-2 text-[12.5px] text-[var(--color-ink-muted)]">You can now include it in a research question.</p>}
    </div>
  );
}

export default function UploadFilingPanel({ onUploaded }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("upload");
  const [file, setFile] = useState(null);
  const [ticker, setTicker] = useState("");
  const [company, setCompany] = useState("");
  const [fiscalYear, setFiscalYear] = useState("");
  const [job, setJob] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef(null);

  function stopPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }

  useEffect(() => stopPolling, []);

  function pollJob(jobId) {
    pollRef.current = setInterval(async () => {
      try {
        const row = await getFilingJob(jobId);
        setJob(row);
        if (row.status === "done" || row.status === "error") {
          stopPolling();
          if (row.status === "done") onUploaded?.();
        }
      } catch {
        stopPolling();
        setJob((j) => ({ ...j, status: "error", error: "Lost connection while checking progress." }));
      }
    }, POLL_MS);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!ticker.trim() || submitting || (mode === "upload" && !file)) return;
    setSubmitting(true);
    setSubmitError(null);
    setJob(null);
    const details = { ticker: ticker.trim(), company: company.trim() || undefined, fiscalYear: fiscalYear.trim() || undefined };
    try {
      const res = mode === "upload" ? await uploadFiling(file, details) : await fetchFiling(details);
      setJob({ status: "queued", chunks_done: 0, chunks_total: null });
      pollJob(res.job_id);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    stopPolling();
    setFile(null);
    setTicker("");
    setCompany("");
    setFiscalYear("");
    setJob(null);
    setSubmitError(null);
  }

  const busy = job && (job.status === "queued" || job.status === "running");
  const progressPct = job?.chunks_total ? Math.round((100 * (job.chunks_done || 0)) / job.chunks_total) : busy ? 8 : 0;
  const canSubmit = ticker.trim() && (mode === "fetch" || file) && !submitting && !busy;

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="group w-full flex items-center gap-3 rounded-[var(--radius-md)] border border-dashed border-[var(--color-border-strong)] px-4 py-3.5 text-left hover:border-[var(--color-brand)] hover:bg-[var(--color-brand-tint)] transition-colors cursor-pointer"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--color-brand-tint)] text-[var(--color-brand)]">
          <PlusIcon className="h-4 w-4" />
        </span>
        <span className="min-w-0">
          <span className="block text-[14px] font-semibold text-[var(--color-ink)]">Add a company</span>
          <span className="block text-[12.5px] text-[var(--color-ink-faint)]">Upload or fetch its annual report</span>
        </span>
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-[var(--radius-md)] border border-[var(--color-border-strong)] bg-[var(--color-surface-muted)] p-4 space-y-3.5 fade-up">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[14px] font-semibold text-[var(--color-ink)]">Add a company</h3>
          <p className="text-[12.5px] text-[var(--color-ink-faint)] mt-0.5">Index its annual report for filings analysis.</p>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={() => {
            setOpen(false);
            reset();
          }}
          className="h-7 w-7 shrink-0 inline-flex items-center justify-center rounded-full text-[var(--color-ink-faint)] hover:text-[var(--color-ink)] hover:bg-[var(--color-surface-sunken)] transition-colors cursor-pointer"
        >
          <CloseIcon className="h-4 w-4" />
        </button>
      </div>

      <div className="flex gap-0.5 p-0.5 rounded-[var(--radius-sm)] bg-[var(--color-surface-sunken)]">
        <ModeTab active={mode === "upload"} onClick={() => { setMode("upload"); reset(); }}>
          Upload PDF
        </ModeTab>
        <ModeTab active={mode === "fetch"} onClick={() => { setMode("fetch"); reset(); }}>
          Find it for me
        </ModeTab>
      </div>

      {mode === "upload" ? (
        <label className="flex flex-col items-center justify-center gap-1.5 rounded-[var(--radius-sm)] border border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface)] px-4 py-5 text-center cursor-pointer hover:border-[var(--color-brand)] transition-colors">
          <UploadIcon className="h-5 w-5 text-[var(--color-ink-faint)]" />
          <span className="text-[13px] font-medium text-[var(--color-ink)] break-all">{file ? file.name : "Choose an annual-report PDF"}</span>
          <span className="text-[12px] text-[var(--color-ink-faint)]">PDF up to 40 MB</span>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            disabled={submitting || busy}
            className="sr-only"
          />
        </label>
      ) : (
        <p className="text-[12.5px] leading-relaxed text-[var(--color-ink-muted)]">
          We'll search for the company's latest annual report and verify it before indexing. Adding the full company name
          improves the match; if none is found, upload the PDF instead.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2.5">
        <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="NSE ticker, e.g. ITC" disabled={submitting || busy} className={inputClass} />
        <input value={fiscalYear} onChange={(e) => setFiscalYear(e.target.value)} placeholder="Year, e.g. 2024-25" disabled={submitting || busy} className={inputClass} />
        <input
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          placeholder={mode === "fetch" ? "Company name, e.g. ITC Limited" : "Company name (optional)"}
          disabled={submitting || busy}
          className={`${inputClass} col-span-2`}
        />
      </div>

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full h-10 text-[13.5px] font-semibold rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-on-brand)] hover:bg-[var(--color-brand-soft)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
      >
        {submitting ? "Starting…" : mode === "upload" ? "Add annual report" : "Find and add annual report"}
      </button>

      {submitError && <p className="text-[12.5px] text-[var(--color-error)]">{submitError}</p>}
      {job && <IngestProgress job={job} progressPct={progressPct} />}
    </form>
  );
}
