import { specialistLabel } from "../progress/StatusBadge";

function ConflictCard({ conflict }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-conflict-border)] bg-[var(--color-conflict-tint)] p-4">
      <div className="flex items-center gap-2 mb-2.5">
        <span className="text-[13px]">⚡</span>
        <h4 className="text-[13.5px] font-semibold text-[var(--color-conflict)]">{conflict.topic}</h4>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
        <div className="rounded-[var(--radius-sm)] bg-[var(--color-surface)]/70 border border-[var(--color-conflict-border)]/60 px-3 py-2">
          <p className="text-[10.5px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] mb-1">
            {specialistLabel(conflict.specialist_a)}
          </p>
          <p className="text-[13px] text-[var(--color-ink)] leading-snug">{conflict.position_a}</p>
        </div>
        <div className="rounded-[var(--radius-sm)] bg-[var(--color-surface)]/70 border border-[var(--color-conflict-border)]/60 px-3 py-2">
          <p className="text-[10.5px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] mb-1">
            {specialistLabel(conflict.specialist_b)}
          </p>
          <p className="text-[13px] text-[var(--color-ink)] leading-snug">{conflict.position_b}</p>
        </div>
      </div>
      <p className="text-[12.5px] text-[var(--color-ink-muted)] leading-relaxed">
        <span className="font-semibold text-[var(--color-conflict)]">Reconciled — </span>
        {conflict.assessment}
      </p>
    </div>
  );
}

export default function ConflictsPanel({ conflicts = [] }) {
  if (conflicts.length === 0) return null;
  return (
    <div>
      <h3 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)] mb-2.5 flex items-center gap-2">
        Conflicting signals
        <span className="text-[11px] font-normal normal-case text-[var(--color-ink-faint)]">
          — flagged and reconciled, not averaged away
        </span>
      </h3>
      <div className="space-y-3">
        {conflicts.map((c, i) => (
          <ConflictCard key={i} conflict={c} />
        ))}
      </div>
    </div>
  );
}
