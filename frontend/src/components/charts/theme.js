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
