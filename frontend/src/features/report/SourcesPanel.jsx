import { useState } from "react";
import { specialistLabel } from "../../lib/labels";

const COLLAPSED_COUNT = 4;

function describeSource(source) {
  const key = source.split(/[\s(,]/)[0];
  const label = specialistLabel(key);
  const detail = source
    .slice(key.length)
    .replace(/^[\s,(]+|[\s)]+$/g, "")
    .replace(/as_of\s*/i, "as of ")
    .trim();
  return detail ? `${label} · ${detail}` : label;
}

export default function SourcesPanel({ sourcesByClaim = {} }) {
  const [expanded, setExpanded] = useState(false);
  const entries = Object.entries(sourcesByClaim);
  if (!entries.length) return null;
  const shown = expanded ? entries : entries.slice(0, COLLAPSED_COUNT);

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <header className="mb-3">
        <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)]">Evidence and sources</h3>
        <p className="text-[12.5px] text-[var(--color-ink-faint)]">Every claim in the report and where it came from</p>
      </header>
      <ol className="divide-y divide-[var(--color-border)]">
        {shown.map(([claim, meta], i) => (
          <li key={i} className="flex gap-3 py-3">
            <span className="mono text-[12px] text-[var(--color-ink-faint)] pt-0.5 w-6 shrink-0">{i + 1}.</span>
            <div className="min-w-0">
              <p className="text-[13.5px] text-[var(--color-ink)] leading-relaxed">{claim}</p>
              <p className="mt-1 text-[12px] text-[var(--color-ink-faint)]">
                {(meta.sources || []).map(describeSource).join("  ·  ") || "Unattributed"}
              </p>
              {meta.caveat && <p className="mt-1 text-[12px] text-[var(--color-ink-muted)]">{meta.caveat}</p>}
            </div>
          </li>
        ))}
      </ol>
      {entries.length > COLLAPSED_COUNT && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-[13px] font-medium text-[var(--color-brand)] hover:text-[var(--color-brand-soft)] transition-colors cursor-pointer"
        >
          {expanded ? "Show fewer" : `Show all ${entries.length} sources`}
        </button>
      )}
    </section>
  );
}
