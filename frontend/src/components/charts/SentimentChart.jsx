import ChartCard from "./ChartCard";
import { SENTIMENT_COLORS } from "./theme";
import { formatDate } from "../../lib/format";

const ORDER = ["positive", "neutral", "negative"];
const LABEL = { positive: "Positive", neutral: "Neutral", negative: "Negative" };

function Chip({ label }) {
  const color = SENTIMENT_COLORS[label] || SENTIMENT_COLORS.neutral;
  return (
    <span className="shrink-0 inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full border border-[var(--color-border-strong)] text-[var(--color-ink-muted)]">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {LABEL[label] || "Neutral"}
    </span>
  );
}

export default function SentimentChart({ sentiment }) {
  if (!sentiment?.breakdown) return null;
  const counts = ORDER.map((k) => ({ key: k, value: sentiment.breakdown[k] || 0 }));
  const total = counts.reduce((s, c) => s + c.value, 0);
  if (!total) return null;
  const overall = sentiment.overall || {};
  const articles = (sentiment.articles || []).slice(0, 6);

  return (
    <ChartCard
      title="News sentiment"
      subtitle={`${total} recent article${total === 1 ? "" : "s"}${sentiment.as_of ? ` · as of ${formatDate(sentiment.as_of)}` : ""}`}
      legend={counts.map((c) => ({ label: `${LABEL[c.key]} (${c.value})`, color: SENTIMENT_COLORS[c.key] }))}
      actions={overall.label && <Chip label={overall.label} />}
    >
      <div
        className="flex h-3 w-full overflow-hidden rounded-full gap-[2px]"
        role="img"
        aria-label={counts.map((c) => `${LABEL[c.key]} ${c.value}`).join(", ")}
      >
        {counts
          .filter((c) => c.value > 0)
          .map((c) => (
            <div
              key={c.key}
              title={`${LABEL[c.key]}: ${c.value}`}
              style={{ width: `${(c.value / total) * 100}%`, background: SENTIMENT_COLORS[c.key] }}
            />
          ))}
      </div>

      {overall.rationale && (
        <p className="mt-4 text-[13px] leading-relaxed text-[var(--color-ink-muted)]">{overall.rationale}</p>
      )}

      {articles.length > 0 && (
        <ul className="mt-4 divide-y divide-[var(--color-border)] border-t border-[var(--color-border)]">
          {articles.map((a, i) => (
            <li key={a.url || i} className="flex items-start justify-between gap-3 py-2.5">
              <div className="min-w-0">
                {a.url ? (
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[13px] text-[var(--color-ink)] hover:text-[var(--color-brand)] transition-colors line-clamp-2"
                  >
                    {a.title}
                  </a>
                ) : (
                  <span className="text-[13px] text-[var(--color-ink)] line-clamp-2">{a.title}</span>
                )}
                {a.published_date && (
                  <span className="text-[11.5px] text-[var(--color-ink-faint)]">{formatDate(a.published_date)}</span>
                )}
              </div>
              <Chip label={a.label} />
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  );
}
