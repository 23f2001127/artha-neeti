function EdgeBadge({ edge, companies }) {
  const isCompanyEdge = edge && companies.some((c) => c.toLowerCase() === String(edge).toLowerCase());
  if (!edge || /^(none|comparable|no edge)/i.test(edge)) {
    return (
      <span className="text-[11.5px] px-2 py-0.5 rounded-full bg-[var(--color-surface-sunken)] text-[var(--color-ink-faint)]">
        comparable
      </span>
    );
  }
  return (
    <span
      className={`text-[11.5px] font-medium px-2 py-0.5 rounded-full ${
        isCompanyEdge
          ? "bg-[var(--color-ok-tint)] text-[var(--color-ok)]"
          : "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)]"
      }`}
    >
      {edge}
    </span>
  );
}

export default function ComparisonView({ comparison }) {
  if (!comparison) return null;
  const companies = comparison.companies || [];

  return (
    <section className="rounded-[var(--radius-lg)] border-2 border-[var(--color-brand)]/15 bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-5">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-brand)]">
          Comparison
        </h2>
        <span className="text-[11px] text-[var(--color-ink-faint)]">{companies.join(" vs. ")}</span>
      </div>

      <p className="text-[14.5px] leading-relaxed text-[var(--color-ink)] mb-4">{comparison.verdict}</p>

      <div className="overflow-x-auto rounded-[var(--radius-md)] border border-[var(--color-border)]">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-[var(--color-surface-muted)] border-b border-[var(--color-border)]">
              <th className="text-left text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] px-4 py-2 w-40">
                Dimension
              </th>
              <th className="text-left text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] px-4 py-2">
                Assessment
              </th>
              <th className="text-left text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] px-4 py-2 w-32">
                Edge
              </th>
            </tr>
          </thead>
          <tbody>
            {(comparison.dimensions || []).map((d, i) => (
              <tr key={i} className="border-b border-[var(--color-border)] last:border-b-0 align-top">
                <td className="px-4 py-3 text-[13px] font-medium text-[var(--color-ink)]">{d.dimension}</td>
                <td className="px-4 py-3 text-[13px] text-[var(--color-ink-muted)] leading-relaxed">
                  {d.assessment}
                </td>
                <td className="px-4 py-3">
                  <EdgeBadge edge={d.edge} companies={companies} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {comparison.caveats?.length > 0 && (
        <ul className="mt-3 space-y-1">
          {comparison.caveats.map((c, i) => (
            <li key={i} className="text-[12px] text-[var(--color-ink-faint)] flex gap-1.5">
              <span>·</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
