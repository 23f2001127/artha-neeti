import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { getJob } from "../../lib/api";

// Curated, not DB-driven - two real completed jobs, picked by hand. The
// tagline is written for presentation; the underlying stored query only
// shows once someone clicks through to the real report, same as it would
// for anyone who typed it themselves. See frontend/README.md.
const FEATURED = [
  {
    jobId: "26274f73-15a8-4984-a52b-03f995265191",
    tagline: "A full research view, with a real tension surfaced",
    badge: "Single company",
  },
  {
    jobId: "269b9645-f7c3-4d29-b1cf-5cf01cc0237f",
    tagline: "A two-stock portfolio, checked for concentration risk",
    badge: "Portfolio analysis",
  },
];

function detailFor(report) {
  if (!report) return null;
  // mode is only ever "single" | "multi" | "none" - portfolio vs. comparison
  // is which of these two fields the multi-mode run actually populated.
  if (report.portfolio) return report.portfolio.diversification || report.portfolio.narrative || null;
  if (report.comparison) return report.comparison.verdict || null;
  const tickers = Object.keys(report.reports || {});
  const only = tickers[0] && report.reports[tickers[0]];
  return only?.executive_summary || null;
}

function GalleryCard({ entry, onView }) {
  const [job, setJob] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getJob(entry.jobId)
      .then((data) => !cancelled && setJob(data))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [entry.jobId]);

  if (failed) return null; // never show a broken card

  const detail = job?.report ? detailFor(job.report) : null;

  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 18 },
        show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1] } },
      }}
      className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 flex flex-col"
    >
      <span className="self-start text-[10.5px] font-medium uppercase tracking-wide px-2 py-0.5 rounded-full bg-[var(--color-brand-tint)] text-[var(--color-brand)] mb-3">
        {entry.badge}
      </span>
      <h3 className="text-[15.5px] font-semibold text-[var(--color-ink)] mb-2 leading-snug">
        {entry.tagline}
      </h3>
      {!job ? (
        <div className="space-y-2 mt-1 mb-4 flex-1">
          <div className="h-3 rounded bg-[var(--color-surface-muted)] animate-pulse w-full" />
          <div className="h-3 rounded bg-[var(--color-surface-muted)] animate-pulse w-5/6" />
          <div className="h-3 rounded bg-[var(--color-surface-muted)] animate-pulse w-2/3" />
        </div>
      ) : (
        <p className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed mb-4 flex-1 line-clamp-4">
          {detail || "Real cited findings, conflicts, and caveats — see the full report."}
        </p>
      )}
      <button
        onClick={() => onView(entry.jobId)}
        className="self-start text-[12.5px] font-medium text-[var(--color-brand)] hover:text-[var(--color-brand-soft)] transition-colors cursor-pointer"
      >
        View full report →
      </button>
    </motion.div>
  );
}

export default function ExampleGallery({ onViewJob }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
      {FEATURED.map((entry) => (
        <GalleryCard key={entry.jobId} entry={entry} onView={onViewJob} />
      ))}
    </div>
  );
}
