import { Bar, BarChart, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import ChartCard from "./ChartCard";
import ChartTooltip from "./ChartTooltip";
import { axisTick } from "./theme";
import { formatPct } from "../../lib/format";

export default function ReturnsChart({ returns }) {
  const data = ["1M", "3M", "6M", "1Y"]
    .map((period) => ({ period, value: returns?.[period] }))
    .filter((d) => typeof d.value === "number");
  if (!data.length) return null;

  return (
    <ChartCard title="Price returns" subtitle="Change in share price over each period">
      <div className="h-[210px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 52, bottom: 4, left: 4 }}>
            <XAxis type="number" hide domain={[(min) => Math.min(0, min), (max) => Math.max(0, max)]} />
            <YAxis type="category" dataKey="period" tick={axisTick} tickLine={false} axisLine={false} width={34} />
            <ReferenceLine x={0} stroke="var(--color-border-strong)" />
            <Tooltip
              cursor={{ fill: "var(--color-surface-muted)" }}
              content={<ChartTooltip formatValue={(v) => formatPct(v, { signed: true })} />}
            />
            <Bar dataKey="value" name="Return" barSize={18} radius={4}>
              {data.map((d) => (
                <Cell key={d.period} fill={d.value >= 0 ? "var(--chart-positive)" : "var(--chart-negative)"} />
              ))}
              <LabelList
                dataKey="value"
                position="right"
                formatter={(v) => formatPct(v, { signed: true })}
                style={{ fill: "var(--color-ink-muted)", fontSize: 11.5, fontWeight: 600 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}
