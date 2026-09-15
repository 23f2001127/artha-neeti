import { specialistLabel } from "../progress/StatusBadge";

const ORDER = ["market_data", "news_sentiment", "filings"];
const ICON = { market_data: "▲", news_sentiment: "◐", filings: "▤" };

export default function SpecialistSections({ sections = {} }) {
  const keys = ORDER.filter((k) => k in sections);
  if (keys.length === 0) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {keys.map((key) => {
        const text = sections[key] || "";
        const unavailable = text.startsWith("Not available");
        return (
          <div
            key={key}
            className={`rounded-[var(--radius-md)] border p-3.5 ${
              unavailable
                ? "border-dashed border-[var(--color-border)] bg-[var(--color-surface-muted)]"
                : "border-[var(--color-border)] bg-[var(--color-surface)]"
            }`}
          >
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="text-[12px] text-[var(--color-ink-faint)]">{ICON[key]}</span>
              <h4 className="text-[11.5px] font-semibold uppercase tracking-wide text-[var(--color-ink-muted)]">
                {specialistLabel(key)}
              </h4>
            </div>
            <p
              className={`text-[13px] leading-relaxed ${
                unavailable ? "text-[var(--color-ink-faint)] italic" : "text-[var(--color-ink)]"
              }`}
            >
              {text}
            </p>
          </div>
        );
      })}
    </div>
  );
}
