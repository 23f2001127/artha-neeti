import { specialistLabel } from "../../lib/labels";

const ORDER = ["market_data", "news_sentiment", "filings"];
const LEGACY_UNAVAILABLE = /^not available/i;

function sectionState(key, sections, unavailable) {
  const text = sections?.[key];
  if (text && !LEGACY_UNAVAILABLE.test(text)) return { text };
  if (unavailable?.[key]) return { reason: unavailable[key] };
  if (text) return { reason: "This source could not be retrieved during this run." };
  return null;
}

export default function AnalysisSections({ sections, unavailable }) {
  const items = ORDER.map((key) => ({ key, ...sectionState(key, sections, unavailable) })).filter(
    (i) => i.text || i.reason,
  );
  if (!items.length) return null;

  return (
    <section>
      <h3 className="text-[16px] font-semibold text-[var(--color-ink)] mb-3">Analysis by source</h3>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {items.map((item) => (
          <article
            key={item.key}
            className={`rounded-[var(--radius-lg)] border p-5 min-w-0 ${
              item.text
                ? "border-[var(--color-border)] bg-[var(--color-surface)]"
                : "border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface-muted)]"
            }`}
          >
            <h4 className="text-[12.5px] font-semibold uppercase tracking-[0.07em] text-[var(--color-brand)] mb-2.5">
              {specialistLabel(item.key)}
            </h4>
            {item.text ? (
              <p className="text-[14px] leading-relaxed text-[var(--color-ink)]">{item.text}</p>
            ) : (
              <>
                <p className="text-[14px] font-medium text-[var(--color-ink-muted)]">Not available in this report</p>
                <p className="mt-1 text-[13px] text-[var(--color-ink-faint)]">{item.reason}</p>
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
