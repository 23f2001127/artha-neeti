import { useId, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import ChartCard from "./ChartCard";
import ChartTooltip from "./ChartTooltip";
import { axisTick, gridProps } from "./theme";
import { formatDate, formatMonth, formatPct, formatPrice, formatShortDate } from "../../lib/format";

const RANGES = [
  { id: "1M", days: 21 },
  { id: "3M", days: 63 },
  { id: "6M", days: 126 },
  { id: "1Y", days: null },
];

function RangeTabs({ value, onChange }) {
  return (
    <div className="inline-flex rounded-[var(--radius-sm)] bg-[var(--color-surface-sunken)] p-0.5" role="tablist">
      {RANGES.map((r) => (
        <button
          key={r.id}
          role="tab"
          aria-selected={value === r.id}
          onClick={() => onChange(r.id)}
          className={`px-2.5 py-1 text-[12px] font-medium rounded-[5px] transition-colors cursor-pointer ${
            value === r.id
              ? "bg-[var(--color-surface-muted)] text-[var(--color-ink)]"
              : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
          }`}
        >
          {r.id}
        </button>
      ))}
    </div>
  );
}

export default function PriceChart({ history, currency, name }) {
  const [range, setRange] = useState("1Y");
  const gradientId = useId();

  const data = useMemo(() => {
    const days = RANGES.find((r) => r.id === range)?.days;
    return days ? history.slice(-days - 1) : history;
  }, [history, range]);

  if (!history?.length) return null;
  const first = data[0]?.close;
  const last = data[data.length - 1]?.close;
  const change = first ? ((last / first) - 1) * 100 : null;
  const closes = data.map((d) => d.close);
  const pad = (Math.max(...closes) - Math.min(...closes)) * 0.08 || 1;

  return (
    <ChartCard
      title="Share price"
      subtitle={
        <>
          <span className="text-[var(--color-ink)] font-semibold tnum">{formatPrice(last, currency)}</span>
          <span className="mx-1.5">·</span>
          <span className="tnum" style={{ color: change >= 0 ? "var(--color-ok)" : "var(--color-error)" }}>
            {formatPct(change, { signed: true })}
          </span>
          <span className="ml-1">over {range}</span>
        </>
      }
      actions={<RangeTabs value={range} onChange={setRange} />}
      footnote={`${name ? `${name} · ` : ""}Daily closing prices, ${formatDate(data[0]?.date)} – ${formatDate(data[data.length - 1]?.date)}`}
    >
      <div className="h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-single)" stopOpacity={0.22} />
                <stop offset="100%" stopColor="var(--chart-single)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid {...gridProps} />
            <XAxis
              dataKey="date"
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              minTickGap={40}
              tickFormatter={range === "1M" ? formatShortDate : formatMonth}
            />
            <YAxis
              domain={[Math.min(...closes) - pad, Math.max(...closes) + pad]}
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(v) => Math.round(v).toLocaleString("en-IN")}
            />
            <Tooltip
              cursor={{ stroke: "var(--color-border-strong)", strokeWidth: 1 }}
              content={<ChartTooltip formatLabel={formatDate} formatValue={(v) => formatPrice(v, currency)} />}
            />
            <Area
              type="monotone"
              dataKey="close"
              name="Close"
              stroke="var(--chart-single)"
              strokeWidth={2}
              fill={`url(#${gradientId})`}
              dot={false}
              activeDot={{ r: 4.5, strokeWidth: 2, stroke: "var(--color-surface)", fill: "var(--chart-single)" }}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}
