import { useEffect, useMemo, useState } from "react";
import { getCompanies } from "../../lib/api";
import { detectFullCoverageMatch } from "../../lib/coverage";
import CoverageStrip from "./CoverageStrip";
import ExampleChips from "./ExampleChips";

export default function QueryView({ onSubmit, submitting, submitError }) {
  const [query, setQuery] = useState("");
  const [companies, setCompanies] = useState([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [companiesError, setCompaniesError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getCompanies()
      .then((data) => {
        if (cancelled) return;
        setCompanies(data.full_coverage?.companies || []);
      })
      .catch((err) => !cancelled && setCompaniesError(err.message))
      .finally(() => !cancelled && setCompaniesLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const match = useMemo(() => detectFullCoverageMatch(query, companies), [query, companies]);

  function handleSubmit(e) {
    e.preventDefault();
    const q = query.trim();
    if (!q || submitting) return;
    onSubmit(q);
  }

  return (
    <div className="mx-auto max-w-[720px] px-6 pt-16 pb-20">
      <div className="fade-up">
        <h1 className="text-[26px] font-semibold tracking-tight text-[var(--color-ink)] mb-2">
          Ask a research question
        </h1>
        <p className="text-[14.5px] text-[var(--color-ink-muted)] leading-relaxed mb-8 max-w-[560px]">
          A planner routes your question to the specialists it actually needs — market data, news
          &amp; sentiment, filings analysis — then reconciles what they find into one cited report.
          Runs take a few minutes; you'll watch it work.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="fade-up" style={{ animationDelay: "60ms" }}>
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] focus-within:border-[var(--color-brand-soft)] transition-colors">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Give me a complete research view on TCS"
            rows={3}
            disabled={submitting}
            className="w-full resize-none bg-transparent px-4 pt-4 pb-2 text-[15px] text-[var(--color-ink)]
                       placeholder:text-[var(--color-ink-faint)] outline-none disabled:opacity-60"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit(e);
            }}
          />
          <div className="flex items-center justify-between px-4 pb-3">
            <span className="text-[11.5px] text-[var(--color-ink-faint)]">⌘/Ctrl + Enter to submit</span>
            <button
              type="submit"
              disabled={!query.trim() || submitting}
              className="text-[13.5px] font-medium px-4 py-1.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)]
                         text-white hover:bg-[var(--color-brand-soft)] transition-colors
                         disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              {submitting ? "Submitting…" : "Run research"}
            </button>
          </div>
        </div>

        <div className="min-h-[26px] mt-2 px-1">
          {query.trim() && match && (
            <p className="text-[12.5px] text-[var(--color-ok)] flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-ok)]" />
              Full coverage detected for <span className="mono font-medium">{match.ticker}</span> — all three
              specialists are available.
            </p>
          )}
          {query.trim() && !match && !companiesLoading && (
            <p className="text-[12.5px] text-[var(--color-running)] flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-running)]" />
              No fully-covered company recognized in this query. If it's about a company outside the
              coverage list below, you'll get market data + news, but not filings analysis.
            </p>
          )}
        </div>

        {submitError && (
          <p className="text-[13px] text-[var(--color-error)] bg-[var(--color-error-tint)] rounded-[var(--radius-sm)] px-3 py-2 mt-1">
            {submitError}
          </p>
        )}
      </form>

      <div className="mt-6 fade-up" style={{ animationDelay: "120ms" }}>
        <ExampleChips onPick={setQuery} disabled={submitting} />
      </div>

      <div className="mt-10 fade-up" style={{ animationDelay: "180ms" }}>
        <CoverageStrip companies={companies} loading={companiesLoading} error={companiesError} />
      </div>
    </div>
  );
}
