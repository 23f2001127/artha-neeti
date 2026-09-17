import UploadFilingPanel from "./UploadFilingPanel";

export default function CoverageStrip({ companies, loading, error, onUploaded }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-center justify-between mb-2.5">
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
          Coverage
        </h3>
        <span className="text-[11px] text-[var(--color-ink-faint)]">what this system can actually answer</span>
      </div>

      {error && (
        <p className="text-[13px] text-[var(--color-error)]">Couldn't load coverage list — {error}</p>
      )}

      {!error && (
        <div className="space-y-3">
          <div>
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-ok)]" />
              <span className="text-[12px] font-medium text-[var(--color-ink)]">
                Full coverage — market data, news &amp; sentiment, and filings analysis
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {loading &&
                Array.from({ length: 10 }).map((_, i) => (
                  <span
                    key={i}
                    className="inline-block h-[22px] w-16 rounded-full bg-[var(--color-surface-muted)] animate-pulse"
                  />
                ))}
              {!loading &&
                companies.map((c) => (
                  <span
                    key={c.ticker}
                    title={c.name}
                    className="mono text-[11.5px] px-2 py-0.5 rounded-full bg-[var(--color-brand-tint)] text-[var(--color-brand)] border border-[var(--color-brand-soft)]/20"
                  >
                    {c.ticker}
                  </span>
                ))}
            </div>
          </div>
          <div className="flex items-start gap-1.5 pt-2.5 border-t border-[var(--color-border)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-skip)] mt-1.5 shrink-0" />
            <p className="text-[12px] text-[var(--color-ink-muted)] leading-snug">
              <span className="font-medium text-[var(--color-ink)]">Any other NSE-listed company</span> —
              market data and news/sentiment still work; filings analysis is skipped (with a stated reason)
              since only the {companies.length || "above"} annual report{companies.length === 1 ? "" : "s"} above
              {companies.length === 1 ? " is" : " are"} ingested — upload one below to add a company.
            </p>
          </div>

          <UploadFilingPanel onUploaded={onUploaded} />
        </div>
      )}
    </div>
  );
}
