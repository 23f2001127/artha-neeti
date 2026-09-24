import { PeerMetricsGrid, RelativePerformanceChart } from "../../components/charts/ComparisonCharts";

function EdgeCell({ edge, companies }) {
  const neutral = !edge || /^(none|comparable|no edge|tie|even)/i.test(edge);
  const isCompany = companies.some((c) => c.toLowerCase() === String(edge).toLowerCase());
  return (
    <span
      className={`inline-flex text-[12px] font-medium px-2.5 py-1 rounded-full ${
        neutral
          ? "bg-[var(--color-surface-sunken)] text-[var(--color-ink-faint)]"
          : isCompany
            ? "bg-[var(--color-brand-tint)] text-[var(--color-ink)]"
            : "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)]"
      }`}
    >
      {neutral ? "Comparable" : edge}
    </span>
  );
}

export default function ComparisonSection({ comparison, visuals, tickers }) {
  if (!comparison && !visuals?.comparison) return null;
  const companies = comparison?.companies || tickers;

  return (
    <div className="space-y-4">
      {comparison?.verdict && (
        <section className="relative overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
          <div className="absolute inset-x-0 top-0 h-[3px] accent-rule-gradient" />
          <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.08em] text-[var(--color-brand)] mb-2.5">Verdict</h3>
          <p className="text-[16px] leading-[1.7] text-[var(--color-ink)]">{comparison.verdict}</p>
        </section>
      )}

      {visuals?.comparison && (
        <>
          <RelativePerformanceChart series={visuals.comparison.relative_performance} tickers={tickers} />
          <PeerMetricsGrid metrics={visuals.comparison.metrics} tickers={tickers} />
        </>
      )}

      {comparison?.dimensions?.length > 0 && (
        <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden">
          <header className="px-5 pt-5 pb-3">
            <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)]">Head-to-head assessment</h3>
            <p className="text-[12.5px] text-[var(--color-ink-faint)]">{companies.join(" vs ")}</p>
          </header>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-y border-[var(--color-border)] bg-[var(--color-surface-muted)]">
                  <th className="text-left text-[12px] font-semibold text-[var(--color-ink-faint)] px-5 py-2.5 w-48">Dimension</th>
                  <th className="text-left text-[12px] font-semibold text-[var(--color-ink-faint)] px-5 py-2.5">Assessment</th>
                  <th className="text-left text-[12px] font-semibold text-[var(--color-ink-faint)] px-5 py-2.5 w-36">Advantage</th>
                </tr>
              </thead>
              <tbody>
                {comparison.dimensions.map((d, i) => (
                  <tr key={i} className="border-b border-[var(--color-border)] last:border-b-0 align-top">
                    <td className="px-5 py-3.5 text-[13.5px] font-semibold text-[var(--color-ink)]">{d.dimension}</td>
                    <td className="px-5 py-3.5 text-[13.5px] leading-relaxed text-[var(--color-ink-muted)]">{d.assessment}</td>
                    <td className="px-5 py-3.5">
                      <EdgeCell edge={d.edge} companies={companies} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {comparison.caveats?.length > 0 && (
            <ul className="px-5 py-4 border-t border-[var(--color-border)] space-y-1.5">
              {comparison.caveats.map((c, i) => (
                <li key={i} className="text-[12.5px] text-[var(--color-ink-faint)]">{c}</li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
