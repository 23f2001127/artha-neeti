import { useState } from "react";
import { specialistLabel } from "../progress/StatusBadge";

const SOURCE_COLORS = {
  market_data: "bg-[var(--color-brand-tint)] text-[var(--color-brand)]",
  news_sentiment: "bg-[#eaf0f7] text-[#2b5a86]",
  filings: "bg-[var(--color-accent-tint)] text-[var(--color-accent)]",
};

function SourceTag({ source }) {
  const key = source.split(/[\s(,]/)[0];
  const cls = SOURCE_COLORS[key] || "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)]";
  return (
    <span className={`text-[10.5px] px-1.5 py-0.5 rounded ${cls}`}>
      {SOURCE_COLORS[key] ? specialistLabel(key) + source.slice(key.length) : source}
    </span>
  );
}

export default function SourcesPanel({ sourcesByClaim = {} }) {
  const [open, setOpen] = useState(true);
  const entries = Object.entries(sourcesByClaim);
  if (entries.length === 0) return null;

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 mb-2.5 cursor-pointer group"
      >
        <h3 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)] group-hover:text-[var(--color-brand)]">
          Sources &amp; claims
        </h3>
        <span className="text-[11px] text-[var(--color-ink-faint)]">
          ({entries.length}) {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <ol className="space-y-2.5 fade-up">
          {entries.map(([claim, meta], i) => (
            <li key={i} className="text-[13px] leading-snug border-b border-[var(--color-border)] pb-2.5 last:border-b-0">
              <div className="flex gap-2">
                <span className="mono text-[11px] text-[var(--color-ink-faint)] shrink-0 mt-0.5">[{i + 1}]</span>
                <div className="flex-1">
                  <p className="text-[var(--color-ink)]">{claim}</p>
                  <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                    {(meta.sources || []).map((s, j) => (
                      <SourceTag key={j} source={s} />
                    ))}
                    {meta.caveat && (
                      <span className="text-[11.5px] text-[var(--color-ink-faint)] italic">— {meta.caveat}</span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
