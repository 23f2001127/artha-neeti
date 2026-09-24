import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import ChartCard from "./ChartCard";
import ChartTooltip from "./ChartTooltip";
import { axisTick, gridProps, seriesColor } from "./theme";
import { formatCroreAxis, formatPct, toCrore } from "../../lib/format";

const fyLabel = (fy) => `FY${String(fy).slice(-2)}`;

export function RevenueProfitChart({ financials }) {
  const data = (financials || [])
    .filter((f) => typeof f.revenue === "number")
    .map((f) => ({ fy: fyLabel(f.fiscal_year), revenue: toCrore(f.revenue), netIncome: toCrore(f.net_income) }));
  if (!data.length) return null;

  const legend = [
    { label: "Revenue", color: seriesColor(0) },
    { label: "Net profit", color: seriesColor(1) },
  ];
  const growth =
    data.length > 1 && data[0].revenue ? ((data[data.length - 1].revenue / data[0].revenue) ** (1 / (data.length - 1)) - 1) * 100 : null;

  return (
    <ChartCard
      title="Revenue and net profit"
      subtitle={growth != null ? `₹ crore, annual · revenue CAGR ${formatPct(growth)}` : "₹ crore, annual"}
      legend={legend}
    >
      <div className="h-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="fy" tick={axisTick} tickLine={false} axisLine={false} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={56} tickFormatter={formatCroreAxis} />
            <Tooltip
              cursor={{ fill: "var(--color-surface-muted)" }}
              content={<ChartTooltip formatValue={(v) => `₹${Math.round(v).toLocaleString("en-IN")} Cr`} />}
            />
            <Bar dataKey="revenue" name="Revenue" fill={seriesColor(0)} radius={[4, 4, 0, 0]} maxBarSize={24} />
            <Bar dataKey="netIncome" name="Net profit" fill={seriesColor(1)} radius={[4, 4, 0, 0]} maxBarSize={24} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

export function MarginTrendChart({ financials }) {
  const data = (financials || [])
    .filter((f) => typeof f.operating_margin === "number" || typeof f.net_margin === "number")
    .map((f) => ({ fy: fyLabel(f.fiscal_year), operating: f.operating_margin, net: f.net_margin }));
  if (data.length < 2) return null;

  const legend = [
    { label: "Operating margin", color: seriesColor(0), shape: "line" },
    { label: "Net margin", color: seriesColor(1), shape: "line" },
  ];

  return (
    <ChartCard title="Margin trend" subtitle="Share of revenue, annual" legend={legend}>
      <div className="h-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="fy" tick={axisTick} tickLine={false} axisLine={false} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={44} tickFormatter={(v) => `${v}%`} domain={["auto", "auto"]} />
            <Tooltip
              cursor={{ stroke: "var(--color-border-strong)" }}
              content={<ChartTooltip formatValue={(v) => formatPct(v)} />}
            />
            {["operating", "net"].map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                name={i === 0 ? "Operating margin" : "Net margin"}
                stroke={seriesColor(i)}
                strokeWidth={2}
                dot={{ r: 4, strokeWidth: 2, stroke: "var(--color-surface)", fill: seriesColor(i) }}
                activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--color-surface)" }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

export function MarginProfileChart({ margins }) {
  const rows = [
    { label: "Gross", value: margins?.gross },
    { label: "EBITDA", value: margins?.ebitda },
    { label: "Operating", value: margins?.operating },
    { label: "Net", value: margins?.net },
  ].filter((r) => typeof r.value === "number");
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => r.value), 1);

  return (
    <ChartCard title="Profitability" subtitle="Latest reported margins">
      <div className="space-y-3.5">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="text-[12.5px] text-[var(--color-ink-muted)]">{r.label} margin</span>
              <span className="text-[13px] font-semibold text-[var(--color-ink)] tnum">{formatPct(r.value)}</span>
            </div>
            <div className="h-2 rounded-full bg-[var(--color-surface-sunken)] overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: `${Math.max(2, (r.value / max) * 100)}%`, background: "var(--chart-single)" }}
              />
            </div>
          </div>
        ))}
      </div>
    </ChartCard>
  );
}
