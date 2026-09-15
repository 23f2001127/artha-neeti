import { useState } from "react";
import { parseRoutingTrace } from "../../lib/parseRoutingTrace";
import { specialistLabel } from "./StatusBadge";

function SpecialistTag({ specialist, reason, kind }) {
  const isSelected = kind === "selected";
  return (
    <div
      className={`group relative flex items-center gap-1.5 text-[12px] px-2 py-1 rounded-[var(--radius-sm)] border
        ${isSelected
          ? "bg-[var(--color-brand-tint)] border-[var(--color-brand-soft)]/25 text-[var(--color-brand)]"
          : "bg-[var(--color-skip-tint)] border-[var(--color-border)] text-[var(--color-skip)]"}`}
    >
      <span>{isSelected ? "●" : "–"}</span>
      <span className="font-medium">{specialistLabel(specialist)}</span>
      {reason && (
        <div
          className="pointer-events-none absolute left-0 top-full mt-1.5 z-20 w-64 rounded-[var(--radius-sm)]
                     border border-[var(--color-border)] bg-[var(--color-ink)] text-white text-[11.5px] leading-snug
                     px-2.5 py-2 opacity-0 group-hover:opacity-100 transition-opacity shadow-lg"
        >
          {reason}
        </div>
      )}
    </div>
  );
}

function CompanyRouting({ c }) {
  return (
    <div className="py-3 first:pt-0 last:pb-0 border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-[13.5px] font-medium text-[var(--color-ink)]">{c.name}</span>
        <span className="mono text-[11px] px-1.5 py-0.5 rounded bg-[var(--color-surface-muted)] text-[var(--color-ink-muted)]">
          {c.ticker}.NS
        </span>
        <span
          className={`text-[10.5px] px-1.5 py-0.5 rounded-full ${
            c.resolvable ? "bg-[var(--color-ok-tint)] text-[var(--color-ok)]" : "bg-[var(--color-error-tint)] text-[var(--color-error)]"
          }`}
        >
          {c.resolvable ? "resolved" : "unresolvable"}
        </span>
        <span
          className={`text-[10.5px] px-1.5 py-0.5 rounded-full ${
            c.inCorpus ? "bg-[var(--color-ok-tint)] text-[var(--color-ok)]" : "bg-[var(--color-surface-sunken)] text-[var(--color-ink-faint)]"
          }`}
        >
          {c.inCorpus ? "in filings corpus" : "not in filings corpus"}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {c.selected?.map((s) => (
          <SpecialistTag key={s.specialist} specialist={s.specialist} reason={s.reason} kind="selected" />
        ))}
        {c.skipped?.map((s) => (
          <SpecialistTag key={s.specialist} specialist={s.specialist} reason={s.reason} kind="skipped" />
        ))}
      </div>
    </div>
  );
}

export default function RoutingPanel({ routingTrace }) {
  const [showTrace, setShowTrace] = useState(false);
  const trace = routingTrace || [];
  const parsed = parseRoutingTrace(trace);

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] fade-up">
      <div className="px-5 pt-4 pb-1 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)]">
          Routing decision
        </h2>
        <span className="text-[11px] text-[var(--color-ink-faint)]">how the planner dispatched this query</span>
      </div>

      {!parsed && (
        <div className="px-5 py-6 text-[13px] text-[var(--color-ink-muted)] flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-running)] pulse-dot" />
          Waiting on the routing decision…
        </div>
      )}

      {parsed && (
        <>
          {parsed.rationale && (
            <p className="mx-5 mt-2 mb-1 text-[13px] text-[var(--color-ink-muted)] leading-relaxed italic border-l-2 border-[var(--color-border-strong)] pl-3">
              "{parsed.rationale}"
            </p>
          )}
          <div className="px-5 pb-2 pt-2">
            {parsed.companies.length === 0 ? (
              <p className="text-[13px] text-[var(--color-ink-muted)] py-2">
                No company could be resolved to a usable data source for this query.
              </p>
            ) : (
              parsed.companies.map((c) => <CompanyRouting key={c.ticker} c={c} />)
            )}
          </div>
          <div className="px-5 pb-4">
            <button
              onClick={() => setShowTrace((v) => !v)}
              className="text-[11.5px] text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)] underline decoration-dotted cursor-pointer"
            >
              {showTrace ? "Hide full trace" : "Show full trace"}
            </button>
            {showTrace && (
              <pre className="mt-2 text-[11px] leading-relaxed text-[var(--color-ink-muted)] bg-[var(--color-surface-muted)] rounded-[var(--radius-sm)] p-3 overflow-x-auto whitespace-pre-wrap">
                {trace.join("\n")}
              </pre>
            )}
          </div>
        </>
      )}
    </section>
  );
}
