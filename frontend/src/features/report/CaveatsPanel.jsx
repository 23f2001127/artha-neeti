import { useState } from "react";

function List({ items }) {
  return (
    <ul className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2.5 text-[13px] leading-relaxed text-[var(--color-ink-muted)]">
          <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-[var(--color-ink-faint)]" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export default function CaveatsPanel({ caveats = [], missingData = [] }) {
  const [open, setOpen] = useState(false);
  const count = caveats.length + missingData.length;
  if (!count) return null;

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 cursor-pointer text-left"
      >
        <span>
          <span className="block text-[14.5px] font-semibold text-[var(--color-ink)]">Limitations and data gaps</span>
          <span className="block text-[12.5px] text-[var(--color-ink-faint)]">
            {count} note{count === 1 ? "" : "s"} on data freshness, coverage and confidence
          </span>
        </span>
        <span className={`text-[var(--color-ink-faint)] transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-4 fade-up">
          {caveats.length > 0 && <List items={caveats} />}
          {missingData.length > 0 && (
            <div className={caveats.length ? "pt-4 border-t border-[var(--color-border)]" : ""}>
              <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-[var(--color-ink-faint)] mb-2">Not available in this report</p>
              <List items={missingData} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}
