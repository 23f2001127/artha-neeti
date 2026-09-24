import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { askFollowup, escalateFollowup, getFollowups, ApiError } from "../../lib/api";

function Turn({ turn, jobId, onEscalate }) {
  const [escalating, setEscalating] = useState(false);
  const [escalateError, setEscalateError] = useState(null);

  async function handleEscalate() {
    setEscalating(true);
    setEscalateError(null);
    try {
      const res = await escalateFollowup(jobId, turn.standalone_query);
      onEscalate(res.job_id);
    } catch (err) {
      setEscalateError(err instanceof ApiError ? err.message : "Couldn't start that research run.");
      setEscalating(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <p className="max-w-[80%] text-[13px] text-[var(--color-bg)] bg-[var(--color-brand)] rounded-[var(--radius-md)] rounded-tr-sm px-3.5 py-2">
          {turn.query}
        </p>
      </div>
      <div className="flex justify-start">
        <div className="max-w-[85%] text-[13px] text-[var(--color-ink)] bg-[var(--color-surface-muted)] rounded-[var(--radius-md)] rounded-tl-sm px-3.5 py-2.5 space-y-1.5">
          {turn.sufficient_data ? (
            <>
              <p>{turn.answer}</p>
              {turn.caveat && (
                <p className="text-[11.5px] text-[var(--color-ink-faint)] italic">— {turn.caveat}</p>
              )}
            </>
          ) : (
            <>
              <p className="text-[var(--color-ink-muted)]">
                This report doesn't cover that — {turn.missing_reason}
              </p>
              <button
                onClick={handleEscalate}
                disabled={escalating}
                className="text-[12px] font-medium px-3 py-1.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)]
                           text-[var(--color-bg)] hover:bg-[var(--color-brand-soft)] transition-colors
                           disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                {escalating ? "Starting…" : "Run full research on this"}
              </button>
              {escalateError && <p className="text-[11.5px] text-[var(--color-error)]">{escalateError}</p>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function FollowUpPanel({ jobId, onEscalate }) {
  const [turns, setTurns] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getFollowups(jobId)
      .then((data) => !cancelled && setTurns(data.turns || []))
      .catch(() => {}) // failing to load history isn't worth blocking on - the ask form still works either way
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  async function handleSubmit(e) {
    e.preventDefault();
    const q = query.trim();
    if (!q || asking) return;
    setAsking(true);
    setAskError(null);
    try {
      const result = await askFollowup(jobId, q);
      if (result.error) throw new ApiError(result.error, 0, result);
      setTurns((prev) => [...prev, { ...result, query: q }]);
      setQuery("");
    } catch (err) {
      setAskError(err instanceof ApiError ? err.message : "Couldn't answer that.");
    } finally {
      setAsking(false);
    }
  }

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] fade-up">
      <div className="px-5 pt-4 pb-3">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)]">
          Ask a follow-up
        </h2>
        <p className="text-[11.5px] text-[var(--color-ink-faint)] mt-0.5">
          Answered from this report when possible — no new research run, no wait.
        </p>
      </div>

      {loaded && turns.length > 0 && (
        <div className="px-5 pb-2 space-y-4 max-h-[420px] overflow-y-auto">
          <AnimatePresence initial={false}>
            {turns.map((t, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25 }}
              >
                <Turn turn={t} jobId={jobId} onEscalate={onEscalate} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      <form onSubmit={handleSubmit} className="px-5 pt-3 pb-4 border-t border-[var(--color-border)] flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. what was its ROE again?"
          disabled={asking}
          className="flex-1 text-[13px] rounded-[var(--radius-sm)] border border-[var(--color-border)]
                     bg-[var(--color-surface)] px-3 py-2 text-[var(--color-ink)]
                     placeholder:text-[var(--color-ink-faint)] outline-none focus:border-[var(--color-brand-soft)]"
        />
        <button
          type="submit"
          disabled={!query.trim() || asking}
          className="text-[13px] font-medium px-4 py-2 rounded-[var(--radius-sm)] bg-[var(--color-brand)]
                     text-[var(--color-bg)] hover:bg-[var(--color-brand-soft)] transition-colors
                     disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shrink-0"
        >
          {asking ? "Asking…" : "Ask"}
        </button>
      </form>
      {askError && <p className="px-5 pb-4 -mt-2 text-[12px] text-[var(--color-error)]">{askError}</p>}
    </section>
  );
}
