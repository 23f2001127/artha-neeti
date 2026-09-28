const CATEGORICAL = [
  "var(--chart-cat-1)",
  "var(--chart-cat-2)",
  "var(--chart-cat-3)",
  "var(--chart-cat-4)",
  "var(--chart-cat-5)",
  "var(--chart-cat-6)",
];

/** Categorical colour by fixed position - never cycled past the palette. */
export function seriesColor(index) {
  return CATEGORICAL[Math.min(index, CATEGORICAL.length - 1)];
}

export const axisTick = { fill: "var(--color-ink-faint)", fontSize: 11 };

export const gridProps = { stroke: "var(--chart-grid)", strokeDasharray: undefined, vertical: false };

export const SENTIMENT_COLORS = {
  positive: "var(--chart-positive)",
  neutral: "var(--chart-neutral)",
  negative: "var(--chart-negative)",
};

/** Series animate on entry unless the user prefers reduced motion. */
export const ANIMATE = !(typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

/** Round, evenly spaced axis values covering [lo, hi], e.g. 250, 300, 350, 400, 450. */
export function niceTicks(lo, hi, count = 4) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (hi === lo) {
    const pad = Math.abs(hi) * 0.1 || 1;
    lo -= pad;
    hi += pad;
  }
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => (hi - lo) / s <= count) ?? 10 * mag;
  const start = Math.floor(lo / step) * step;
  const end = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

/** Axis domain for horizontal bars with room at each end for the value label. */
export function paddedBarDomain(values, share = 0.3) {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const pad = (hi - lo || 1) * share;
  return [lo < 0 ? lo - pad : 0, hi > 0 ? hi + pad : 0];
}

/** LabelList content that puts the value just past the bar's end, left for negative bars. */
export function barEndLabel(format) {
  return function BarEndLabel({ x, y, width, height, value }) {
    if (typeof value !== "number") return null;
    const left = Math.min(x, x + width);
    const right = Math.max(x, x + width);
    const negative = value < 0;
    return (
      <text
        x={negative ? left - 6 : right + 6}
        y={y + height / 2}
        dominantBaseline="central"
        textAnchor={negative ? "end" : "start"}
        style={{ fill: "var(--color-ink-muted)", fontSize: 11.5, fontWeight: 600 }}
      >
        {format(value)}
      </text>
    );
  };
}

/** The first date of each calendar month in a daily series, for month-labelled axes. */
export function monthStartTicks(data, key = "date") {
  const ticks = [];
  let previous = null;
  for (const row of data) {
    const month = String(row[key]).slice(0, 7);
    if (month !== previous) {
      if (previous !== null) ticks.push(row[key]);
      previous = month;
    }
  }
  return ticks;
}
