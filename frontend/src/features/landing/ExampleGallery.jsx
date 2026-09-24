import { useEffect, useState } from "react";
import { getJob, getVisuals } from "../../lib/api";
import Sparkline from "../../components/charts/Sparkline";
import { ArrowRightIcon } from "../../components/ui/icons";
import { formatPct, formatPrice } from "../../lib/format";

const FEATURED = [
  {
    jobId: "26274f73-15a8-4984-a52b-03f995265191",
    kind: "Company deep dive",
    title: "Tata Consultancy Services",
    blurb: "Fundamentals, filings and price action reconciled into one view, with the tension between them made explicit.",
  },
  {
    jobId: "269b9645-f7c3-4d29-b1cf-5cf01cc0237f",
    kind: "Portfolio review",
    title: "TCS + Infosys portfolio",
    blurb: "An equal-weight two-stock portfolio checked for sector concentration, weighted valuation and shared risks.",
  },
];

function summaryFor(report) {
  if (!report) return null;
  if (report.portfolio) return report.portfolio.diversification || report.portfolio.narrative;
  if (report.comparison) return report.comparison.verdict;
  const first = Object.values(report.reports || {})[0];
  return first?.executive_summary;
}

function ExampleCard({ entry, onView }) {
  const [job, setJob] = useState(null);
  const [visuals, setVisuals] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getJob(entry.jobId)
      .then((data) => !cancelled && setJob(data))
      .catch(() => !cancelled && setFailed(true));
    getVisuals(entry.jobId)
      .then((data) => !cancelled && setVisuals(data))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [entry.jobId]);

  if (failed) return null;

  const packs = Object.entries(visuals?.companies || {});
  const summary = summaryFor(job?.report);

  return (
    <article className="group rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden flex flex-col hover:border-[var(--color-border-strong)] transition-colors">
      <div className="px-6 pt-6">
        <span className="text-[11.5px] font-semibold uppercase tracking-[0.08em] text-[var(--color-brand)]">
          {entry.kind}
        </span>
        <h3 className="mt-2 text-[19px] font-semibold text-[var(--color-ink)]">{entry.title}</h3>
        <p className="mt-2 text-[13.5px] leading-relaxed text-[var(--color-ink-muted)]">{entry.blurb}</p>
      </div>

      <div className="mt-5 px-6 grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.max(1, packs.length)}, minmax(0, 1fr))` }}>
        {packs.length ? (
          packs.map(([ticker, pack]) => (
            <div key={ticker} className="rounded-[var(--radius-md)] bg-[var(--color-surface-muted)] p-3 min-w-0">
              <div className="flex items-baseline justify-between gap-2">
                <span className="mono text-[12px] font-medium text-[var(--color-ink)]">{ticker}</span>
                <span className="text-[12px] tnum text-[var(--color-ink-muted)]">
                  {formatPrice(pack.kpis?.price, pack.currency)}
                </span>
              </div>
              <Sparkline values={(pack.price_history || []).map((p) => p.close)} height={48} />
              <p className="text-[11.5px] text-[var(--color-ink-faint)] tnum">1Y {formatPct(pack.returns?.["1Y"], { signed: true })}</p>
            </div>
          ))
        ) : (
          <div className="h-[92px] rounded-[var(--radius-md)] bg-[var(--color-surface-muted)] animate-pulse" />
        )}
      </div>

      <div className="px-6 pt-4 pb-6 flex-1 flex flex-col">
        {summary ? (
          <p className="text-[13px] leading-relaxed text-[var(--color-ink-faint)] line-clamp-3 flex-1">{summary}</p>
        ) : (
          <div className="space-y-2 flex-1">
            <div className="h-3 rounded bg-[var(--color-surface-muted)] animate-pulse" />
            <div className="h-3 w-4/5 rounded bg-[var(--color-surface-muted)] animate-pulse" />
          </div>
        )}
        <button
          onClick={() => onView(entry.jobId)}
          className="mt-5 self-start inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-[var(--color-brand)] hover:text-[var(--color-brand-soft)] transition-colors cursor-pointer"
        >
          Open report
          <ArrowRightIcon className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
        </button>
      </div>
    </article>
  );
}

export default function ExampleGallery({ onViewJob }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {FEATURED.map((entry) => (
        <ExampleCard key={entry.jobId} entry={entry} onView={onViewJob} />
      ))}
    </div>
  );
}
