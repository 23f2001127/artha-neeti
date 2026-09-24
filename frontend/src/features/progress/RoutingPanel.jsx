import { specialistLabel } from "../../lib/labels";

function Source({ specialist, reason, selected }) {
  return (
    <li className="flex gap-3 py-2">
      <span
        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${selected ? "bg-[var(--color-ok)]" : "bg-[var(--color-skip)] opacity-60"}`}
      />
      <div className="min-w-0">
        <p className={`text-[13.5px] font-medium ${selected ? "text-[var(--color-ink)]" : "text-[var(--color-ink-faint)]"}`}>
          {specialistLabel(specialist)}
          {!selected && <span className="ml-1.5 text-[12px] font-normal">· not used</span>}
        </p>
        {reason && <p className="text-[12.5px] leading-relaxed text-[var(--color-ink-faint)]">{reason}</p>}
      </div>
    </li>
  );
}

function CompanyPlan({ company }) {
  const specialists = company.specialists || [];
  const ordered = [...specialists.filter((s) => s.selected), ...specialists.filter((s) => !s.selected)];
  return (
    <div className="py-4 first:pt-0 last:pb-0 border-b border-[var(--color-border)] last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[14.5px] font-semibold text-[var(--color-ink)]">{company.name}</span>
        <span className="mono text-[12px] text-[var(--color-ink-faint)]">{company.ticker}</span>
        {company.weight_pct != null && (
          <span className="text-[12px] px-2 py-0.5 rounded-full bg-[var(--color-brand-tint)] text-[var(--color-ink)]">
            {company.weight_pct}% of portfolio
          </span>
        )}
        {!company.resolvable && (
          <span className="text-[12px] px-2 py-0.5 rounded-full bg-[var(--color-error-tint)] text-[var(--color-ink)]">
            Not listed on NSE
          </span>
        )}
      </div>
      <ul className="mt-1">
        {ordered.map((s) => (
          <Source key={s.specialist} specialist={s.specialist} reason={s.reason} selected={s.selected} />
        ))}
      </ul>
    </div>
  );
}

/** The planner's research plan: which sources each company gets, and why. */
export default function RoutingPanel({ routing, embedded = false }) {
  const companies = routing?.companies_identified || [];
  const body = !routing ? (
    <p className="flex items-center gap-2 py-2 text-[13.5px] text-[var(--color-ink-muted)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-running)] pulse-dot" />
      Identifying companies and planning the research…
    </p>
  ) : (
    <>
      {routing.rationale && (
        <p className="mb-4 text-[13.5px] leading-relaxed text-[var(--color-ink-muted)]">{routing.rationale}</p>
      )}
      {companies.length === 0 ? (
        <p className="text-[13.5px] text-[var(--color-ink-muted)]">No listed company could be identified in this question.</p>
      ) : (
        companies.map((c) => <CompanyPlan key={c.ticker} company={c} />)
      )}
    </>
  );

  if (embedded) return body;
  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
      <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)]">Research plan</h3>
      <p className="text-[12.5px] text-[var(--color-ink-faint)] mb-4">Sources selected for each company</p>
      {body}
    </section>
  );
}
