import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import ChartCard from "../../components/charts/ChartCard";
import ChartTooltip from "../../components/charts/ChartTooltip";
import { seriesColor } from "../../components/charts/theme";
import { PeerMetricsGrid } from "../../components/charts/ComparisonCharts";
import { formatMultiple, formatPct } from "../../lib/format";

function Donut({ title, subtitle, segments }) {
  if (!segments.length) return null;
  const legend = segments.map((s, i) => ({ label: `${s.label}  ${formatPct(s.pct)}`, color: seriesColor(i) }));
  return (
    <ChartCard title={title} subtitle={subtitle} legend={legend}>
      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip content={<ChartTooltip formatValue={(v) => formatPct(v)} />} />
            <Pie
              data={segments}
              dataKey="pct"
              nameKey="label"
              innerRadius="62%"
              outerRadius="92%"
              paddingAngle={segments.length > 1 ? 2 : 0}
              stroke="var(--color-surface)"
              strokeWidth={2}
            >
              {segments.map((s, i) => (
                <Cell key={s.label} fill={seriesColor(i)} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-5 py-4">
      <p className="text-[12px] text-[var(--color-ink-faint)]">{label}</p>
      <p className="mt-1 text-[24px] font-semibold text-[var(--color-ink)]">{value}</p>
    </div>
  );
}

export default function PortfolioSection({ portfolio, visuals, tickers }) {
  if (!portfolio) return null;
  const holdings = (portfolio.holdings || []).map((h) => ({ label: h.ticker, pct: h.weight_pct }));
  const sectors = Object.entries(portfolio.sector_allocation_pct || {}).map(([label, pct]) => ({ label, pct }));

  return (
    <div className="space-y-4">
      <section className="relative overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <div className="absolute inset-x-0 top-0 h-[3px] accent-rule-gradient" />
        <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.08em] text-[var(--color-brand)] mb-2.5">Portfolio view</h3>
        <p className="text-[16px] leading-[1.7] text-[var(--color-ink)]">{portfolio.narrative}</p>
      </section>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Stat label="Weighted P/E" value={formatMultiple(portfolio.weighted_pe_ratio)} />
        <Stat label="Weighted return on equity" value={formatPct(portfolio.weighted_roe)} />
        <Stat label="Weighted dividend yield" value={formatPct(portfolio.weighted_dividend_yield_pct, { digits: 2 })} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Donut title="Holdings" subtitle="Portfolio weight by company" segments={holdings} />
        <Donut title="Sector exposure" subtitle="Share of the portfolio by sector" segments={sectors} />
      </div>

      {visuals?.comparison && <PeerMetricsGrid metrics={visuals.comparison.metrics} tickers={tickers} />}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
          <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)] mb-2">Diversification</h3>
          <p className="text-[14px] leading-relaxed text-[var(--color-ink-muted)]">{portfolio.diversification}</p>
        </section>
        {portfolio.concentration_risks?.length > 0 && (
          <section className="rounded-[var(--radius-lg)] border border-[var(--color-conflict-border)] bg-[var(--color-conflict-tint)] p-5">
            <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)] mb-3">Concentration risks</h3>
            <ul className="space-y-2.5">
              {portfolio.concentration_risks.map((risk, i) => (
                <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed text-[var(--color-ink)]">
                  <span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-conflict)]" />
                  {risk}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {(portfolio.caveats?.length > 0 || portfolio.metrics_unavailable_for?.length > 0) && (
        <ul className="space-y-1.5 px-1">
          {portfolio.metrics_unavailable_for?.length > 0 && (
            <li className="text-[12.5px] text-[var(--color-ink-faint)]">
              Weighted metrics exclude {portfolio.metrics_unavailable_for.join(", ")}; market data was unavailable.
            </li>
          )}
          {(portfolio.caveats || []).map((c, i) => (
            <li key={i} className="text-[12.5px] text-[var(--color-ink-faint)]">{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
