import StatusBadge from "./StatusBadge";
import { specialistLabel } from "../../lib/labels";

const ORDER = ["market_data", "news_sentiment", "filings"];

export default function SpecialistGrid({ specialistStatus, names = {} }) {
  const tickers = Object.keys(specialistStatus || {});

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)]">Progress by company</h3>
      <p className="text-[12.5px] text-[var(--color-ink-faint)] mb-4">Live status of each data source</p>

      {tickers.length === 0 ? (
        <p className="flex items-center gap-2 text-[13.5px] text-[var(--color-ink-muted)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-ink-faint)]" />
          Waiting for the research plan…
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {tickers.map((ticker) => (
            <div key={ticker} className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-4 min-w-0">
              <p className="text-[14px] font-semibold text-[var(--color-ink)] truncate">
                {names[ticker] || ticker}
                <span className="ml-2 mono text-[12px] font-normal text-[var(--color-ink-faint)]">{ticker}</span>
              </p>
              <ul className="mt-3 space-y-2.5">
                {ORDER.filter((sp) => sp in specialistStatus[ticker]).map((sp) => (
                  <li key={sp} className="flex items-center justify-between gap-3">
                    <span className="text-[13px] text-[var(--color-ink)]">{specialistLabel(sp)}</span>
                    <StatusBadge status={specialistStatus[ticker][sp]} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
