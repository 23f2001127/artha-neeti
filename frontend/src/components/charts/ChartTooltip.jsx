/** Recharts tooltip content: an inverted chip, identical in both themes. */
export default function ChartTooltip({ active, payload, label, formatLabel, formatValue }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="rounded-[var(--radius-sm)] px-3 py-2 shadow-lg text-[12px] min-w-[140px]"
      style={{ background: "var(--color-tooltip-bg)", color: "var(--color-tooltip-ink)" }}
    >
      {label != null && (
        <p className="mb-1.5 font-medium opacity-80">{formatLabel ? formatLabel(label) : label}</p>
      )}
      <div className="space-y-1">
        {payload.map((entry) => (
          <div key={entry.dataKey ?? entry.name} className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5 opacity-85">
              <span className="h-2 w-2 rounded-full" style={{ background: entry.color || entry.payload?.fill }} />
              {entry.name}
            </span>
            <span className="tnum font-semibold">
              {formatValue ? formatValue(entry.value, entry) : entry.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
