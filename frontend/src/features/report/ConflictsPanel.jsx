import { specialistLabel } from "../../lib/labels";

function WarningIcon(props) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M12 3l9 16H3z" />
      <path d="M12 10v4M12 17h.01" />
    </svg>
  );
}

function Position({ specialist, text }) {
  return (
    <div className="rounded-[var(--radius-sm)] bg-[var(--color-surface)] border border-[var(--color-border)] px-3.5 py-3">
      <p className="text-[11.5px] font-semibold uppercase tracking-[0.06em] text-[var(--color-ink-faint)] mb-1">
        {specialistLabel(specialist)}
      </p>
      <p className="text-[13.5px] text-[var(--color-ink)] leading-relaxed">{text}</p>
    </div>
  );
}

export default function ConflictsPanel({ conflicts = [] }) {
  if (!conflicts.length) return null;
  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-conflict-border)] bg-[var(--color-conflict-tint)] p-5">
      <header className="flex items-center gap-2.5 mb-4">
        <WarningIcon className="h-5 w-5 text-[var(--color-conflict)]" />
        <div>
          <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)]">Where the signals disagree</h3>
          <p className="text-[12.5px] text-[var(--color-ink-muted)]">Conflicting evidence is surfaced and assessed, not averaged away.</p>
        </div>
      </header>
      <div className="space-y-4">
        {conflicts.map((c, i) => (
          <div key={i}>
            <h4 className="text-[14px] font-semibold text-[var(--color-ink)] mb-2.5">{c.topic}</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Position specialist={c.specialist_a} text={c.position_a} />
              <Position specialist={c.specialist_b} text={c.position_b} />
            </div>
            <p className="mt-3 text-[13.5px] text-[var(--color-ink-muted)] leading-relaxed">
              <span className="font-semibold text-[var(--color-ink)]">Assessment. </span>
              {c.assessment}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
