// Model-written report text sometimes carries internal identifiers and raw
// timestamps: "(news_sentiment, as_of 2026-09-21T08:30:00Z)". Shown to readers
// as "(news sentiment, as of 21 Sep 2026)".

const TOOL = /\bget_([a-z0-9_]+)\b/g;
const SNAKE = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;
const ISO = /\b(\d{4})-(\d{2})-(\d{2})(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?\b/g;
const PROVIDER_LIMIT = /\bLLM (?:quota|rate)(?: limit)?\b/gi;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Fields that hold identifiers the UI maps to labels itself.
const RAW_FIELDS = new Set(["sources", "specialist_a", "specialist_b", "specialists_used", "reasoning_trace", "model"]);

export function readable(text) {
  if (typeof text !== "string") return text;
  return text
    .replace(/\u2011/g, "-")
    .replace(PROVIDER_LIMIT, "usage limit")
    .replace(ISO, (match, y, m, d) => (MONTHS[Number(m) - 1] ? `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}` : match))
    .replace(TOOL, "$1")
    .replace(SNAKE, (match) => match.replace(/_/g, " "));
}

function walk(value, key) {
  if (typeof value === "string") return RAW_FIELDS.has(key) ? value : readable(value);
  if (Array.isArray(value)) return RAW_FIELDS.has(key) ? value : value.map((v) => walk(v, key));
  if (value && typeof value === "object") {
    const renameKeys = key === "sources_by_claim";
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [renameKeys ? readable(k) : k, walk(v, k)]));
  }
  return value;
}

/** A report with its reader-facing text normalized; routing data is left as is. */
export function readableReport(report) {
  if (!report) return report;
  return {
    ...report,
    reports: walk(report.reports, "reports"),
    comparison: walk(report.comparison, "comparison"),
    portfolio: walk(report.portfolio, "portfolio"),
  };
}
