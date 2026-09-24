export function Legend({ items }) {
  if (!items?.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-ink-muted)]">
          <span
            className={item.shape === "line" ? "h-[2px] w-3.5 rounded-full" : "h-2.5 w-2.5 rounded-[3px]"}
            style={{ background: item.color }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

export default function ChartCard({ title, subtitle, legend, actions, footnote, className = "", children }) {
  return (
    <section
      className={`rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 flex flex-col min-w-0 ${className}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)]">{title}</h3>
          {subtitle && <p className="text-[12.5px] text-[var(--color-ink-faint)] mt-0.5">{subtitle}</p>}
        </div>
        {actions}
      </header>
      {legend && (
        <div className="mb-3">
          <Legend items={legend} />
        </div>
      )}
      <div className="flex-1 min-h-0">{children}</div>
      {footnote && <p className="mt-3 text-[11.5px] text-[var(--color-ink-faint)]">{footnote}</p>}
    </section>
  );
}
