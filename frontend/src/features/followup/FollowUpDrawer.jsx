import { useEffect, useRef, useState } from "react";
import { askFollowup, escalateFollowup, getFollowups, ApiError } from "../../lib/api";
import { ChatIcon, CloseIcon, SendIcon } from "../../components/ui/icons";

const SUGGESTIONS = [
  "What are the biggest risks here?",
  "How does the valuation compare with its history?",
  "Summarise this in three bullet points",
];

function Bubble({ side, children }) {
  const mine = side === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[88%] text-[13.5px] leading-relaxed rounded-[var(--radius-md)] px-3.5 py-2.5 ${
          mine
            ? "bg-[var(--color-brand)] text-[var(--color-on-brand)] rounded-br-sm"
            : "bg-[var(--color-surface-muted)] text-[var(--color-ink)] rounded-bl-sm"
        }`}
      >
        {children}
      </div>
    </div>
  );
}

function Answer({ turn, jobId, onOpenJob }) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState(null);

  async function runFullResearch() {
    setStarting(true);
    setError(null);
    try {
      const res = await escalateFollowup(jobId, turn.standalone_query);
      onOpenJob(res.job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start a new research run.");
      setStarting(false);
    }
  }

  if (turn.sufficient_data) {
    return (
      <Bubble side="assistant">
        <p>{turn.answer}</p>
        {turn.caveat && <p className="mt-1.5 text-[12px] text-[var(--color-ink-faint)]">{turn.caveat}</p>}
      </Bubble>
    );
  }
  return (
    <Bubble side="assistant">
      <p className="text-[var(--color-ink-muted)]">This report doesn't cover that. {turn.missing_reason}</p>
      <button
        onClick={runFullResearch}
        disabled={starting}
        className="mt-2.5 text-[12.5px] font-semibold px-3 py-1.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-on-brand)] hover:bg-[var(--color-brand-soft)] transition-colors disabled:opacity-50 cursor-pointer"
      >
        {starting ? "Starting…" : "Run new research"}
      </button>
      {error && <p className="mt-1.5 text-[12px] text-[var(--color-error)]">{error}</p>}
    </Bubble>
  );
}

export default function FollowUpDrawer({ jobId, onOpenJob }) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState([]);
  const [query, setQuery] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    getFollowups(jobId)
      .then((data) => !cancelled && setTurns(data.turns || []))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    inputRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, asking, open]);

  async function ask(text) {
    const q = text.trim();
    if (!q || asking) return;
    setAsking(true);
    setError(null);
    setQuery("");
    try {
      const result = await askFollowup(jobId, q);
      if (result.error) throw new ApiError(result.error, 0, result);
      setTurns((prev) => [...prev, { ...result, query: q }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't answer that right now.");
      setQuery(q);
    } finally {
      setAsking(false);
    }
  }

  return (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-40 inline-flex items-center gap-2 h-12 pl-4 pr-5 rounded-full bg-[var(--color-brand)] text-[var(--color-on-brand)] text-[14px] font-semibold shadow-[var(--shadow-card)] hover:bg-[var(--color-brand-soft)] transition-colors cursor-pointer"
        >
          <ChatIcon className="h-5 w-5" />
          Ask about this report
          {turns.length > 0 && (
            <span className="ml-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-[var(--color-on-brand)] px-1.5 text-[11px] text-[var(--color-brand)]">
              {turns.length}
            </span>
          )}
        </button>
      )}

      {open && (
        <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Follow-up questions">
          <div className="absolute inset-0 bg-black/40 overlay-in" onClick={() => setOpen(false)} />
          <aside className="drawer-in absolute right-0 top-0 h-full w-full max-w-[440px] flex flex-col bg-[var(--color-surface)] border-l border-[var(--color-border)] shadow-2xl">
            <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--color-border)]">
              <div>
                <h2 className="text-[15px] font-semibold text-[var(--color-ink)]">Ask about this report</h2>
                <p className="text-[12.5px] text-[var(--color-ink-faint)] mt-0.5">Answers are grounded in this report's findings.</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="h-8 w-8 inline-flex items-center justify-center rounded-full text-[var(--color-ink-faint)] hover:text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)] transition-colors cursor-pointer"
              >
                <CloseIcon className="h-4 w-4" />
              </button>
            </header>

            <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-5 space-y-3">
              {turns.length === 0 && !asking && (
                <div className="space-y-2">
                  <p className="text-[12.5px] text-[var(--color-ink-faint)] mb-3">Try asking</p>
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => ask(s)}
                      className="w-full text-left text-[13.5px] text-[var(--color-ink-muted)] rounded-[var(--radius-md)] border border-[var(--color-border)] px-3.5 py-2.5 hover:border-[var(--color-border-strong)] hover:text-[var(--color-ink)] transition-colors cursor-pointer"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {turns.map((t, i) => (
                <div key={i} className="space-y-3">
                  <Bubble side="user">{t.query}</Bubble>
                  <Answer turn={t} jobId={jobId} onOpenJob={onOpenJob} />
                </div>
              ))}
              {asking && (
                <Bubble side="assistant">
                  <span className="inline-flex items-center gap-1.5 text-[var(--color-ink-faint)]">
                    <span className="h-1.5 w-1.5 rounded-full bg-current pulse-dot" />
                    Thinking
                  </span>
                </Bubble>
              )}
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                ask(query);
              }}
              className="border-t border-[var(--color-border)] p-4"
            >
              {error && <p className="mb-2 text-[12.5px] text-[var(--color-error)]">{error}</p>}
              <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-border-strong)] bg-[var(--color-bg-elevated)] pl-3.5 pr-1.5 py-1.5 focus-within:border-[var(--color-brand)] transition-colors">
                <input
                  ref={inputRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Ask a follow-up question"
                  disabled={asking}
                  className="flex-1 bg-transparent text-[14px] text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)] outline-none py-1.5"
                />
                <button
                  type="submit"
                  disabled={!query.trim() || asking}
                  aria-label="Send"
                  className="h-9 w-9 inline-flex items-center justify-center rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-on-brand)] hover:bg-[var(--color-brand-soft)] transition-colors disabled:opacity-40 cursor-pointer"
                >
                  <SendIcon className="h-4 w-4" />
                </button>
              </div>
            </form>
          </aside>
        </div>
      )}
    </>
  );
}
