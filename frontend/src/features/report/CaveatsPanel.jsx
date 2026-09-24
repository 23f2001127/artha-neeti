import { useState } from "react";

export default function CaveatsPanel({ caveats = [], missingData = [] }) {
  const [open, setOpen] = useState(false);
  const count = caveats.length + missingData.length;
  if (count === 0) return null;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-[var(--color-surface-muted)] hover:bg-[var(--color-surface-sunken)] transition-colors cursor-pointer"
      >
        <span className="flex items-center gap-2 text-[12.5px] font-medium text-[var(--color-ink-muted)]">
          <span className="inline-flex items-center justify-center h-4 w-4 rounded-full border border-[var(--color-ink-faint)] text-[10px] leading-none">
            i
          </span>
          Caveats &amp; limitations
          <span className="text-[var(--color-ink-faint)] font-normal">({count})</span>
        </span>
        <span className="text-[11px] text-[var(--color-ink-faint)]">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="px-4 py-3 bg-[var(--color-surface)] space-y-3 fade-up">
          {caveats.length > 0 && (
            <ul className="space-y-1.5">
              {caveats.map((c, i) => (
                <li key={i} className="text-[12.5px] text-[var(--color-ink-muted)] leading-relaxed flex gap-2">
                  <span className="text-[var(--color-ink-faint)] shrink-0">·</span>
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          )}
          {missingData.length > 0 && (
            <div className={caveats.length > 0 ? "pt-2 border-t border-[var(--color-border)]" : ""}>
              <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] mb-1.5">
                What's missing
              </p>
              <ul className="space-y-1.5">
                {missingData.map((m, i) => (
                  <li key={i} className="text-[12.5px] text-[var(--color-ink-muted)] leading-relaxed flex gap-2">
                    <span className="text-[var(--color-ink-faint)] shrink-0">·</span>
                    <span>{m}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
