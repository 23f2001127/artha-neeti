function fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Radial elapsed-time meter. Determinate against the historical estimate when
 * one exists; otherwise an indeterminate spinning arc, never an invented
 * percentage.
 */
export default function TimeGauge({ elapsed, estimatedDuration, wrappingUp, size = 88 }) {
  const stroke = Math.max(5, Math.round(size / 12));
  const radius = (size - stroke) / 2;
  const circ = 2 * Math.PI * radius;
  const determinate = estimatedDuration != null;
  const fraction = determinate ? Math.min(1, Math.max(0, elapsed / estimatedDuration)) : 0;
  const color = wrappingUp ? "var(--color-ok)" : "var(--color-running)";
  const c = size / 2;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${fmt(elapsed)} elapsed`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={c} cy={c} r={radius} fill="none" stroke="var(--color-border)" strokeWidth={stroke} />
        {determinate ? (
          <circle
            cx={c}
            cy={c}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={circ * (1 - fraction)}
            transform={`rotate(-90 ${c} ${c})`}
            style={{ transition: "stroke-dashoffset 0.6s ease, stroke 0.4s ease" }}
          />
        ) : (
          <circle
            className="spin-slow"
            cx={c}
            cy={c}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${circ * 0.26} ${circ * 0.74}`}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="tnum text-[17px] font-semibold text-[var(--color-ink)] leading-none">{fmt(elapsed)}</span>
        <span className="mt-1 text-[10.5px] text-[var(--color-ink-faint)] leading-none">elapsed</span>
      </div>
    </div>
  );
}
