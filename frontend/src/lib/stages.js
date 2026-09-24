const TOOL_STAGES = {
  get_price_history: "Loading price history",
  get_fundamentals: "Reading fundamentals",
  get_ratios: "Calculating ratios",
  get_peer_comparison: "Comparing peers",
  search_news: "Searching the news",
  get_company_news: "Collecting recent news",
  get_sentiment: "Scoring sentiment",
  get_corporate_announcements: "Checking announcements",
  search_filing: "Searching the annual report",
  get_financial_statement_section: "Reading financial statements",
  compare_yoy_metrics: "Comparing year-on-year figures",
};

const PHASE_STAGES = {
  "connecting...": "Starting",
  "thinking...": "Analysing",
  "reading results...": "Reviewing results",
  "writing summary...": "Writing summary",
};

/** Human-readable label for a live specialist status string. */
export function friendlyStage(raw) {
  if (!raw || raw === "pending") return "Queued";
  if (PHASE_STAGES[raw]) return PHASE_STAGES[raw];
  const tool = raw.match(/^calling\s+([\w-]+)/)?.[1];
  if (tool) return TOOL_STAGES[tool] || "Gathering data";
  return raw;
}
