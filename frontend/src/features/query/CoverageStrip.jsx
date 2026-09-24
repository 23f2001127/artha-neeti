import UploadFilingPanel from "./UploadFilingPanel";

export default function CoverageStrip({ companies, loading, error, onUploaded }) {
  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h2 className="text-[14.5px] font-semibold text-[var(--color-ink)]">Coverage</h2>
      <p className="text-[12.5px] text-[var(--color-ink-faint)] mb-4">What each report can draw on</p>

      {error ? (
        <p className="text-[13.5px] text-[var(--color-ink-muted)]">Coverage details are unavailable right now.</p>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="flex items-center gap-2 text-[13.5px] font-medium text-[var(--color-ink)]">
              <span className="h-2 w-2 rounded-full bg-[var(--color-ok)]" />
              Full coverage
            </p>
            <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">
              Market data, news sentiment and annual-report analysis.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {loading
                ? Array.from({ length: 8 }).map((_, i) => (
                    <span key={i} className="inline-block h-6 w-16 rounded-full bg-[var(--color-surface-muted)] animate-pulse" />
                  ))
                : companies.map((c) => (
                    <span
                      key={c.ticker}
                      title={c.name}
                      className="mono text-[12px] px-2.5 py-1 rounded-full border border-[var(--color-border)] bg-[var(--color-surface-muted)] text-[var(--color-ink)]"
                    >
                      {c.ticker}
                    </span>
                  ))}
            </div>
          </div>
          <div className="pt-4 border-t border-[var(--color-border)]">
            <p className="flex items-center gap-2 text-[13.5px] font-medium text-[var(--color-ink)]">
              <span className="h-2 w-2 rounded-full bg-[var(--color-skip)]" />
              Every other NSE company
            </p>
            <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">
              Market data and news sentiment. Add the company's annual report below to include filings analysis.
            </p>
          </div>
          <UploadFilingPanel onUploaded={onUploaded} />
        </div>
      )}
    </section>
  );
}
