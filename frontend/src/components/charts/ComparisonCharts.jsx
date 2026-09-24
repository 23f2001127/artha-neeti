import { Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import ChartCard from "./ChartCard";
import ChartTooltip from "./ChartTooltip";
import { axisTick, gridProps, seriesColor } from "./theme";
import { formatByUnit, formatDate, formatMonth, formatPct } from "../../lib/format";

export function RelativePerformanceChart({ series, tickers }) {
  if (!series?.length || tickers.length < 2) return null;
  const last = series[series.length - 1];
  const legend = tickers.map((t, i) => ({
    label: `${t}  ${formatPct(last[t] - 100, { signed: true })}`,
    color: seriesColor(i),
    shape: "line",
  }));

  return (
    <ChartCard
      title="Relative performance"
      subtitle={`Share price rebased to 100 on ${formatDate(series[0].date)}`}
      legend={legend}
    >
      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="date" tick={axisTick} tickLine={false} axisLine={false} minTickGap={40} tickFormatter={formatMonth} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={40} domain={["auto", "auto"]} />
            <ReferenceLine y={100} stroke="var(--color-border-strong)" />
            <Tooltip
              cursor={{ stroke: "var(--color-border-strong)" }}
              content={<ChartTooltip formatLabel={formatDate} formatValue={(v) => v.toFixed(1)} />}
            />
            {tickers.map((t, i) => (
              <Line
                key={t}
                type="monotone"
                dataKey={t}
                name={t}
                stroke={seriesColor(i)}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4.5, strokeWidth: 2, stroke: "var(--color-surface)" }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function MetricMini({ metric, tickers }) {
  const data = tickers.map((t, i) => ({ ticker: t, value: metric.values[t], color: seriesColor(i) }));
  const valid = data.filter((d) => typeof d.value === "number");
  if (!valid.length) return null;
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-3.5 min-w-0">
      <p className="text-[12.5px] font-medium text-[var(--color-ink-muted)] mb-2">{metric.label}</p>
      <div style={{ height: 30 + tickers.length * 26 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 0 }}>
            <XAxis type="number" hide domain={[(min) => Math.min(0, min), (max) => Math.max(0, max)]} />
            <YAxis type="category" dataKey="ticker" tick={axisTick} tickLine={false} axisLine={false} width={64} />
            <Tooltip cursor={false} content={<ChartTooltip formatValue={(v) => formatByUnit(v, metric.unit)} />} />
            <Bar dataKey="value" name={metric.label} barSize={14} radius={4}>
              {data.map((d) => (
                <Cell key={d.ticker} fill={d.color} />
              ))}
              <LabelList
                dataKey="value"
                position="right"
                formatter={(v) => formatByUnit(v, metric.unit)}
                style={{ fill: "var(--color-ink-muted)", fontSize: 11.5, fontWeight: 600 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function PeerMetricsGrid({ metrics, tickers }) {
  if (!metrics?.length) return null;
  const legend = tickers.map((t, i) => ({ label: t, color: seriesColor(i) }));
  return (
    <ChartCard title="Key metrics side by side" subtitle="Each metric on its own scale" legend={legend}>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {metrics.map((m) => (
          <MetricMini key={m.key} metric={m} tickers={tickers} />
        ))}
      </div>
    </ChartCard>
  );
}
