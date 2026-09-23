const SIZE = 52;
const STROKE = 5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRC = 2 * Math.PI * RADIUS;

function fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** A compact radial time meter, replacing a plain "X:XX elapsed" text row.
 *
 * Determinate (elapsed / estimatedDuration, clamped [0,1]) once a real
 * historical ETA exists; an indeterminate spinning arc otherwise - this
 * never fakes a percentage the way a hardcoded guess would, matching
 * etaLabel()'s existing "no estimate yet" honesty in ProgressView.jsx.
 *
 * Color reuses the app's already-established status vocabulary rather than
 * inventing a new hue: amber (--color-running) while in progress, green
 * (--color-ok) once wrapping up - never color-alone, the elapsed time is
 * also a direct text label in the center. */
export default function TimeGauge({ elapsed, estimatedDuration, wrappingUp }) {
  const determinate = estimatedDuration != null;
  const fraction = determinate ? Math.min(1, Math.max(0, elapsed / estimatedDuration)) : 0;
  const offset = CIRC * (1 - fraction);
  const color = wrappingUp ? "var(--color-ok)" : "var(--color-running)";

  return (
    <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }} role="img" aria-label={`${fmt(elapsed)} elapsed`}>
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke="var(--color-border-strong)" strokeWidth={STROKE} />
        {determinate ? (
          <circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={color}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={CIRC}
            strokeDashoffset={offset}
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
            style={{ transition: "stroke-dashoffset 0.6s ease, stroke 0.4s ease" }}
          />
        ) : (
          <circle
            className="spin-slow"
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke="var(--color-running)"
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={`${CIRC * 0.26} ${CIRC * 0.74}`}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="tnum mono text-[11px] font-medium text-[var(--color-ink)]">{fmt(elapsed)}</span>
      </div>
    </div>
  );
}
