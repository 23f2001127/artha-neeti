import { useEffect, useMemo, useState } from "react";
import { getCompanies } from "../../lib/api";
import { detectFullCoverageMatch } from "../../lib/coverage";
import { ArrowRightIcon } from "../../components/ui/icons";
import CoverageStrip from "./CoverageStrip";
import ExampleChips from "./ExampleChips";

const INCLUDED = [
  "Share price, valuation and profitability charts",
  "News sentiment across recent coverage",
  "Annual-report analysis with page citations",
  "Flagged conflicts between sources",
  "Shareable link and PDF export",
];

export default function QueryView({ onSubmit, submitting, submitError }) {
  const [query, setQuery] = useState("");
  const [companies, setCompanies] = useState([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [companiesError, setCompaniesError] = useState(null);

  function refreshCompanies() {
    return getCompanies()
      .then((data) => setCompanies(data.full_coverage?.companies || []))
      .catch((err) => setCompaniesError(err.message));
  }

  useEffect(() => {
    let cancelled = false;
    getCompanies()
      .then((data) => !cancelled && setCompanies(data.full_coverage?.companies || []))
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
    if (q && !submitting) onSubmit(q);
  }

  return (
    <div className="page py-12 grid grid-cols-1 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-8 items-start">
      <div className="min-w-0 fade-up">
        <p className="text-[12.5px] font-semibold uppercase tracking-[0.1em] text-[var(--color-brand)]">New research report</p>
        <h1 className="font-display mt-3 text-[34px] sm:text-[42px] leading-tight font-semibold text-[var(--color-ink)]">
          What would you like to research?
        </h1>
        <p className="mt-3 max-w-[640px] text-[15.5px] leading-relaxed text-[var(--color-ink-muted)]">
          Ask about a single company, compare several, or describe a portfolio you hold. Reports take a few minutes to
          prepare.
        </p>

        <form onSubmit={handleSubmit} className="mt-8">
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-strong)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] focus-within:border-[var(--color-brand)] transition-colors">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Give me a complete research view on TCS"
              rows={4}
              disabled={submitting}
              aria-label="Research question"
              className="w-full resize-none bg-transparent px-5 pt-5 pb-2 text-[16px] leading-relaxed text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)] outline-none disabled:opacity-60"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit(e);
              }}
            />
            <div className="flex items-center justify-between gap-3 px-5 pb-4">
              <span className="hidden sm:inline text-[12.5px] text-[var(--color-ink-faint)]">Ctrl + Enter to submit</span>
              <button
                type="submit"
                disabled={!query.trim() || submitting}
                className="ml-auto inline-flex items-center gap-2 h-11 px-5 text-[14.5px] font-semibold rounded-[var(--radius-md)] bg-[var(--color-brand)] text-[var(--color-on-brand)] hover:bg-[var(--color-brand-soft)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                {submitting ? "Starting…" : "Generate report"}
                {!submitting && <ArrowRightIcon className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <div className="min-h-[28px] mt-3 px-1">
            {query.trim() && match && (
              <p className="flex items-center gap-2 text-[13px] text-[var(--color-ink-muted)]">
                <span className="h-2 w-2 rounded-full bg-[var(--color-ok)]" />
                Full coverage for {match.name || match.ticker}: market data, news and annual-report analysis.
              </p>
            )}
            {query.trim() && !match && !companiesLoading && (
              <p className="flex items-center gap-2 text-[13px] text-[var(--color-ink-muted)]">
                <span className="h-2 w-2 rounded-full bg-[var(--color-skip)]" />
                Market data and news cover every NSE company. Annual-report analysis is limited to the companies listed on the right.
              </p>
            )}
          </div>

          {submitError && (
            <p className="mt-2 rounded-[var(--radius-md)] bg-[var(--color-error-tint)] px-4 py-3 text-[13.5px] text-[var(--color-ink)]">
              {submitError}
            </p>
          )}
        </form>

        <div className="mt-8">
          <p className="text-[13px] font-medium text-[var(--color-ink-faint)] mb-3">Try one of these</p>
          <ExampleChips onPick={setQuery} disabled={submitting} />
        </div>

        <div className="mt-10 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <p className="text-[14px] font-semibold text-[var(--color-ink)] mb-3">Every report includes</p>
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
            {INCLUDED.map((item) => (
              <li key={item} className="flex items-start gap-2.5 text-[13.5px] text-[var(--color-ink-muted)]">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand)]" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <aside className="min-w-0 fade-up" style={{ animationDelay: "80ms" }}>
        <CoverageStrip companies={companies} loading={companiesLoading} error={companiesError} onUploaded={refreshCompanies} />
      </aside>
    </div>
  );
}
