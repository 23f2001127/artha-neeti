import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { uploadFiling, fetchFiling, getFilingJob, ApiError } from "../../lib/api";

const POLL_MS = 1500;

function ModeTab({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-[11.5px] font-medium px-2.5 py-1 rounded-[var(--radius-sm)] transition-colors cursor-pointer ${
        active
          ? "bg-[var(--color-brand-tint)] text-[var(--color-brand)]"
          : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
      }`}
    >
      {children}
    </button>
  );
}

export default function UploadFilingPanel({ onUploaded }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("upload"); // "upload" | "fetch"
  const [file, setFile] = useState(null);
  const [ticker, setTicker] = useState("");
  const [company, setCompany] = useState("");
  const [fiscalYear, setFiscalYear] = useState("");
  const [job, setJob] = useState(null); // {status, chunks_done, chunks_total, detail, error}
  const [submitError, setSubmitError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef(null);

  function stopPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }

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
    if (!ticker.trim() || submitting) return;
    if (mode === "upload" && !file) return;
    setSubmitting(true);
    setSubmitError(null);
    setJob(null);
    try {
      const res =
        mode === "upload"
          ? await uploadFiling(file, {
              ticker: ticker.trim(),
              company: company.trim() || undefined,
              fiscalYear: fiscalYear.trim() || undefined,
            })
          : await fetchFiling({
              ticker: ticker.trim(),
              company: company.trim() || undefined,
              fiscalYear: fiscalYear.trim() || undefined,
            });
      setJob({ status: "queued", chunks_done: 0, chunks_total: null });
      pollJob(res.job_id);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Request failed.");
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
  const progressPct =
    job?.chunks_total ? Math.round((100 * (job.chunks_done || 0)) / job.chunks_total) : busy ? 8 : 0;
  const canSubmit = ticker.trim() && (mode === "fetch" || file) && !submitting && !busy;

  return (
    <div className="pt-2.5 border-t border-[var(--color-border)] mt-1">
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="text-[12px] text-[var(--color-brand)] hover:text-[var(--color-brand-soft)] underline decoration-dotted cursor-pointer"
        >
          Don't see your company? Add its annual report →
        </button>
      ) : (
        <motion.form
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          onSubmit={handleSubmit}
          className="space-y-2.5"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              <ModeTab active={mode === "upload"} onClick={() => { setMode("upload"); reset(); }}>
                Upload a PDF
              </ModeTab>
              <ModeTab active={mode === "fetch"} onClick={() => { setMode("fetch"); reset(); }}>
                Auto-fetch from the web
              </ModeTab>
            </div>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                reset();
              }}
              className="text-[11px] text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)] cursor-pointer"
            >
              Cancel
            </button>
          </div>

          {mode === "upload" ? (
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              disabled={submitting || busy}
              className="block w-full text-[12px] text-[var(--color-ink-muted)] file:mr-3 file:px-3 file:py-1.5
                         file:rounded-[var(--radius-sm)] file:border-0 file:text-[12px] file:font-medium
                         file:bg-[var(--color-brand-tint)] file:text-[var(--color-brand)] cursor-pointer"
            />
          ) : (
            <p className="text-[11.5px] text-[var(--color-ink-faint)] leading-snug">
              Best-effort: searches the web for a directly-downloadable annual-report PDF and verifies it
              actually mentions the company before ingesting it. A more precise company name improves the
              odds — if it can't find one, switch to upload.
            </p>
          )}

          <div className="grid grid-cols-3 gap-2">
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="Ticker (e.g. ITC)"
              disabled={submitting || busy}
              className="col-span-1 text-[12.5px] rounded-[var(--radius-sm)] border border-[var(--color-border)]
                         bg-[var(--color-surface)] px-2.5 py-1.5 text-[var(--color-ink)]
                         placeholder:text-[var(--color-ink-faint)] outline-none focus:border-[var(--color-brand-soft)]"
            />
            <input
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder={mode === "fetch" ? "Company name (e.g. ITC Limited)" : "Company name (optional)"}
              disabled={submitting || busy}
              className="col-span-1 text-[12.5px] rounded-[var(--radius-sm)] border border-[var(--color-border)]
                         bg-[var(--color-surface)] px-2.5 py-1.5 text-[var(--color-ink)]
                         placeholder:text-[var(--color-ink-faint)] outline-none focus:border-[var(--color-brand-soft)]"
            />
            <input
              value={fiscalYear}
              onChange={(e) => setFiscalYear(e.target.value)}
              placeholder="FY (optional, e.g. 2024-25)"
              disabled={submitting || busy}
              className="col-span-1 text-[12.5px] rounded-[var(--radius-sm)] border border-[var(--color-border)]
                         bg-[var(--color-surface)] px-2.5 py-1.5 text-[var(--color-ink)]
                         placeholder:text-[var(--color-ink-faint)] outline-none focus:border-[var(--color-brand-soft)]"
            />
          </div>

          <div className="flex items-center justify-between">
            <p className="text-[11px] text-[var(--color-ink-faint)]">
              {mode === "upload"
                ? "PDF only, up to 40MB. Embedding runs against a shared free-tier quota — a large report can take a few minutes."
                : "Searches, downloads, and verifies before ingesting — can take a little longer than a direct upload."}
            </p>
            <button
              type="submit"
              disabled={!canSubmit}
              className="text-[12px] font-medium px-3 py-1.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)]
                         text-[var(--color-bg)] hover:bg-[var(--color-brand-soft)] transition-colors
                         disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shrink-0 ml-3"
            >
              {submitting ? "Starting…" : mode === "upload" ? "Ingest" : "Fetch automatically"}
            </button>
          </div>

          {submitError && <p className="text-[12px] text-[var(--color-error)]">{submitError}</p>}

          {/* No AnimatePresence: its exit transition never completes with
              this framer-motion/React 19 pairing (confirmed live elsewhere
              in this app) and would leave this panel stacked in the DOM
              forever once `job` resets. Plain conditional rendering unmounts
              it immediately and correctly, just without a fade-out. */}
          {job && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded-[var(--radius-sm)] border border-[var(--color-border)] bg-[var(--color-surface-muted)] px-3 py-2.5"
              >
                {job.status !== "error" && (
                  <>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[12px] text-[var(--color-ink)]">
                        {job.status === "done"
                          ? "Ingested"
                          : job.detail || "Embedding chunks…"}
                      </span>
                      <span className="mono text-[11px] text-[var(--color-ink-faint)]">
                        {job.status === "done"
                          ? `${job.chunks} chunks`
                          : job.chunks_total
                            ? `${job.chunks_done}/${job.chunks_total}`
                            : "starting…"}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-[var(--color-surface-sunken)] overflow-hidden">
                      <motion.div
                        className={`h-full rounded-full ${job.status === "done" ? "bg-[var(--color-ok)]" : "bg-[var(--color-running)]"}`}
                        animate={{ width: `${job.status === "done" ? 100 : progressPct}%` }}
                        transition={{ duration: 0.4 }}
                      />
                    </div>
                    {job.status === "done" && (
                      <p className="text-[11.5px] text-[var(--color-ok)] mt-1.5">
                        Available now — try a query about it.
                      </p>
                    )}
                  </>
                )}
                {job.status === "error" && (
                  <p className="text-[12px] text-[var(--color-error)]">{job.error || "Ingestion failed."}</p>
                )}
              </motion.div>
          )}
        </motion.form>
      )}
    </div>
  );
}
