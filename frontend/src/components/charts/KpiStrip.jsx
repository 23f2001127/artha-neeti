import { formatMoney, formatMultiple, formatPct, formatPrice } from "../../lib/format";

function Tile({ label, value, detail }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3.5 min-w-0">
      <p className="text-[12px] text-[var(--color-ink-faint)] truncate">{label}</p>
      <p className="mt-1 text-[20px] font-semibold text-[var(--color-ink)] truncate">{value}</p>
      {detail && <p className="mt-0.5 text-[11.5px] text-[var(--color-ink-faint)] truncate">{detail}</p>}
    </div>
  );
}

function RangeTile({ low, high, price, currency }) {
  const valid = [low, high, price].every((v) => typeof v === "number") && high > low;
  const pos = valid ? Math.min(100, Math.max(0, ((price - low) / (high - low)) * 100)) : null;
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3.5 min-w-0 col-span-2">
      <p className="text-[12px] text-[var(--color-ink-faint)]">52-week range</p>
      {valid ? (
        <>
          <div className="relative mt-3.5 h-1.5 rounded-full bg-[var(--color-surface-sunken)]">
            <div className="absolute inset-y-0 left-0 rounded-full accent-rule-gradient" style={{ width: `${pos}%` }} />
            <div
              className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--color-surface)] bg-[var(--color-brand)]"
              style={{ left: `${pos}%` }}
              title={`Current: ${formatPrice(price, currency)}`}
            />
          </div>
          <div className="mt-2 flex justify-between text-[11.5px] text-[var(--color-ink-faint)] tnum">
            <span>{formatPrice(low, currency)}</span>
            <span>{formatPrice(high, currency)}</span>
          </div>
        </>
      ) : (
        <p className="mt-1 text-[20px] font-semibold text-[var(--color-ink)]">—</p>
      )}
    </div>
  );
}

export default function KpiStrip({ pack }) {
  const k = pack?.kpis || {};
  const c = pack?.currency;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
      <Tile label="Share price" value={formatPrice(k.price, c)} detail={pack?.sector || undefined} />
      <Tile label="Market cap" value={formatMoney(k.market_cap, c)} />
      <Tile label="P/E (TTM)" value={formatMultiple(k.pe_ratio)} detail={k.forward_pe ? `Forward ${formatMultiple(k.forward_pe)}` : undefined} />
      <Tile label="Return on equity" value={formatPct(k.roe)} detail={k.roa ? `ROA ${formatPct(k.roa)}` : undefined} />
      <Tile label="Dividend yield" value={formatPct(k.dividend_yield_pct, { digits: 2 })} />
      <Tile label="Debt to equity" value={formatMultiple(k.debt_to_equity, 2)} detail={k.current_ratio ? `Current ratio ${k.current_ratio}` : undefined} />
      <RangeTile low={k.week52_low} high={k.week52_high} price={k.price} currency={c} />
    </div>
  );
}
