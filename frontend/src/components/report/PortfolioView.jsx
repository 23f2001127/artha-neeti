// Categorical hues in a fixed order (never cycled/reassigned) - validated with
// the dataviz skill's palette validator against both themes' surfaces; see
// index.css. A holding/sector always gets the slot matching its position in
// the (stable, weight-sorted) list, not a color keyed to its identity, so
// re-running a similar query doesn't imply anything by matching colors.
const CAT_SLOTS = 6;
function catColor(i) {
  return `var(--chart-cat-${(i % CAT_SLOTS) + 1})`;
}

function AllocationBar({ segments, totalLabel }) {
  // Every segment is direct-labeled (never color-alone) - the bar needs no
  // separate legend box because each piece already names itself. Realistic
  // portfolio/sector counts here are small (2-6), so this holds; beyond that
  // a legend would be needed instead of relying on in-bar labels.
  return (
    <div>
      <div className="flex h-7 rounded-[var(--radius-sm)] overflow-hidden border border-[var(--color-border)]">
        {segments.map((s, i) => (
          <div
            key={s.key}
            style={{ width: `${Math.max(s.pct, 0.5)}%`, backgroundColor: catColor(i) }}
            className="first:rounded-l-[var(--radius-sm)] last:rounded-r-[var(--radius-sm)] border-r-2 border-[var(--color-surface)] last:border-r-0"
            title={`${s.label} — ${s.pct}%`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-2.5">
        {segments.map((s, i) => (
          <div key={s.key} className="flex items-center gap-1.5 text-[12px]">
            <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ backgroundColor: catColor(i) }} />
            <span className="text-[var(--color-ink)] font-medium">{s.label}</span>
            <span className="mono text-[var(--color-ink-faint)]">{s.pct}%</span>
          </div>
        ))}
      </div>
      {totalLabel && <p className="text-[11px] text-[var(--color-ink-faint)] mt-1.5">{totalLabel}</p>}
    </div>
  );
}

function MetricTile({ label, value, suffix = "" }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface-muted)] px-4 py-3">
      <p className="text-[10.5px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] mb-1">
        {label}
      </p>
      <p className="mono text-[19px] font-semibold text-[var(--color-ink)]">
        {value == null ? "—" : `${value}${suffix}`}
      </p>
    </div>
  );
}

export default function PortfolioView({ portfolio }) {
  if (!portfolio) return null;
  const holdings = portfolio.holdings || [];

  const holdingSegments = holdings.map((h) => ({
    key: h.ticker, label: h.ticker, pct: h.weight_pct,
  }));
  const sectorEntries = Object.entries(portfolio.sector_allocation_pct || {});
  const sectorSegments = sectorEntries.map(([sector, pct]) => ({
    key: sector, label: sector, pct,
  }));

  return (
    <section className="rounded-[var(--radius-lg)] border-2 border-[var(--color-brand)]/15 bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-5">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-brand)]">
          Portfolio analysis
        </h2>
        <span className="text-[11px] text-[var(--color-ink-faint)]">
          {holdings.length} holding{holdings.length === 1 ? "" : "s"}
        </span>
      </div>

      <p className="text-[14.5px] leading-relaxed text-[var(--color-ink)] mb-5">{portfolio.narrative}</p>

      <div className="mb-5">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] mb-2">
          Allocation
        </h3>
        <AllocationBar segments={holdingSegments} />
      </div>

      {sectorSegments.length > 0 && (
        <div className="mb-5">
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] mb-2">
            Sector allocation
          </h3>
          <AllocationBar segments={sectorSegments} />
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 mb-5">
        <MetricTile label="Weighted P/E" value={portfolio.weighted_pe_ratio} />
        <MetricTile label="Weighted ROE" value={portfolio.weighted_roe} suffix="%" />
        <MetricTile label="Weighted dividend yield" value={portfolio.weighted_dividend_yield_pct} suffix="%" />
      </div>

      <div className="mb-5">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-ink-faint)] mb-1.5">
          Diversification
        </h3>
        <p className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed">{portfolio.diversification}</p>
      </div>

      {portfolio.concentration_risks?.length > 0 && (
        <div className="mb-5">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)] mb-2.5 flex items-center gap-2">
            Concentration risks
            <span className="text-[11px] font-normal normal-case text-[var(--color-ink-faint)]">
              — flagged, not averaged away
            </span>
          </h3>
          <div className="space-y-2">
            {portfolio.concentration_risks.map((risk, i) => (
              <div
                key={i}
                className="rounded-[var(--radius-md)] border border-[var(--color-conflict-border)] bg-[var(--color-conflict-tint)] px-3.5 py-2.5 flex items-start gap-2"
              >
                <span className="text-[13px] shrink-0">⚡</span>
                <p className="text-[12.5px] text-[var(--color-ink)] leading-relaxed">{risk}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {portfolio.metrics_unavailable_for?.length > 0 && (
        <p className="text-[11.5px] text-[var(--color-ink-faint)] mb-3">
          Weighted metrics exclude {portfolio.metrics_unavailable_for.join(", ")} — market data wasn't available for it.
        </p>
      )}

      {portfolio.caveats?.length > 0 && (
        <ul className="space-y-1">
          {portfolio.caveats.map((c, i) => (
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
