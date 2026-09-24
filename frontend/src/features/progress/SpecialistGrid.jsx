import StatusBadge, { specialistLabel } from "./StatusBadge";

const ORDER = ["market_data", "news_sentiment", "filings"];

export default function SpecialistGrid({ specialistStatus }) {
  const tickers = Object.keys(specialistStatus || {});
  if (tickers.length === 0) {
    return (
      <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] px-5 py-6 fade-up">
        <div className="flex items-center gap-2 text-[13px] text-[var(--color-ink-muted)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-ink-faint)]" />
          Specialists haven't been dispatched yet.
        </div>
      </section>
    );
  }

  const columns = ORDER.filter((sp) => tickers.some((t) => sp in specialistStatus[t]));
  const multi = tickers.length > 1;

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] fade-up">
      <div className="px-5 pt-4 pb-3 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)]">
          Specialist progress
        </h2>
        <span className="text-[11px] text-[var(--color-ink-faint)]">
          {multi ? `${tickers.length} companies × ${columns.length} specialists` : "live"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-t border-b border-[var(--color-border)] bg-[var(--color-surface-muted)]">
              {multi && (
                <th className="text-left text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] px-5 py-2 w-32">
                  Company
                </th>
              )}
              {columns.map((sp) => (
                <th
                  key={sp}
                  className={`text-left text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] py-2 ${multi ? "px-3" : "px-5"}`}
                >
                  {specialistLabel(sp)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tickers.map((ticker) => (
              <tr key={ticker} className="border-b border-[var(--color-border)] last:border-b-0">
                {multi && (
                  <td className="px-5 py-2.5 mono text-[12.5px] text-[var(--color-ink)] font-medium">{ticker}</td>
                )}
                {columns.map((sp) => {
                  const status = specialistStatus[ticker]?.[sp];
                  return (
                    <td key={sp} className={`py-2.5 ${multi ? "px-3" : "px-5"}`}>
                      {status ? (
                        <StatusBadge status={status} />
                      ) : (
                        <span className="text-[12px] text-[var(--color-ink-faint)]">— not routed</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
