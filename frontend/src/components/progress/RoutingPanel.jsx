import { useState } from "react";
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
                     bg-[var(--color-tooltip-bg)] text-[var(--color-tooltip-ink)] text-[11.5px] leading-snug
                     px-2.5 py-2 opacity-0 group-hover:opacity-100 transition-opacity shadow-lg"
        >
          {reason}
        </div>
      )}
    </div>
  );
}

function CompanyRouting({ c }) {
  const specialists = c.specialists || [];
  const selected = specialists.filter((s) => s.selected);
  const skipped = specialists.filter((s) => !s.selected);
  return (
    <div className="py-3 first:pt-0 last:pb-0 border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="text-[13.5px] font-medium text-[var(--color-ink)]">{c.name}</span>
        <span className="mono text-[11px] px-1.5 py-0.5 rounded bg-[var(--color-surface-muted)] text-[var(--color-ink-muted)]">
          {c.ticker}.NS
        </span>
        {c.weight_pct != null && (
          <span className="mono text-[10.5px] px-1.5 py-0.5 rounded-full bg-[var(--color-brand-tint)] text-[var(--color-brand)]">
            {c.weight_pct}% of portfolio
          </span>
        )}
        <span
          className={`text-[10.5px] px-1.5 py-0.5 rounded-full ${
            c.resolvable ? "bg-[var(--color-ok-tint)] text-[var(--color-ok)]" : "bg-[var(--color-error-tint)] text-[var(--color-error)]"
          }`}
        >
          {c.resolvable ? "resolved" : "unresolvable"}
        </span>
        <span
          className={`text-[10.5px] px-1.5 py-0.5 rounded-full ${
            c.in_filings_corpus ? "bg-[var(--color-ok-tint)] text-[var(--color-ok)]" : "bg-[var(--color-surface-sunken)] text-[var(--color-ink-faint)]"
          }`}
        >
          {c.in_filings_corpus ? "in filings corpus" : "not in filings corpus"}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {selected.map((s) => (
          <SpecialistTag key={s.specialist} specialist={s.specialist} reason={s.reason} kind="selected" />
        ))}
        {skipped.map((s) => (
          <SpecialistTag key={s.specialist} specialist={s.specialist} reason={s.reason} kind="skipped" />
        ))}
      </div>
    </div>
  );
}

/** Renders the Planner's structured routing decision - the same `routing`
 * object whether the job is still running (pushed live the moment the route
 * node finishes) or already `done` (report.routing). No more reconstructing
 * this from raw trace lines. */
export default function RoutingPanel({ routing, routingTrace }) {
  const [showTrace, setShowTrace] = useState(false);
  const trace = routingTrace || [];
  const companies = routing?.companies_identified || [];

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] fade-up">
      <div className="px-5 pt-4 pb-1 flex items-center justify-between">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)]">
          Routing decision
        </h2>
        <span className="text-[11px] text-[var(--color-ink-faint)]">how the planner dispatched this query</span>
      </div>

      {!routing && (
        <div className="px-5 py-6 text-[13px] text-[var(--color-ink-muted)] flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-running)] pulse-dot" />
          Waiting on the routing decision…
        </div>
      )}

      {routing && (
        <>
          {routing.rationale && (
            <p className="mx-5 mt-2 mb-1 text-[13px] text-[var(--color-ink-muted)] leading-relaxed italic border-l-2 border-[var(--color-border-strong)] pl-3">
              "{routing.rationale}"
            </p>
          )}
          <div className="px-5 pb-2 pt-2">
            {companies.length === 0 ? (
              <p className="text-[13px] text-[var(--color-ink-muted)] py-2">
                No company could be resolved to a usable data source for this query.
              </p>
            ) : (
              companies.map((c) => <CompanyRouting key={c.ticker} c={c} />)
            )}
          </div>
          {trace.length > 0 && (
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
          )}
        </>
      )}
    </section>
  );
}
