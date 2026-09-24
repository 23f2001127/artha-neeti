const SPECIALISTS = [
  { id: "market_data", label: "Market Data", sub: "yfinance" },
  { id: "news_sentiment", label: "News + Sentiment", sub: "Tavily · Gemini" },
  { id: "filings", label: "Filings RAG", sub: "pgvector" },
];

/** A cell's raw value is "pending" | "ok" | "error: <msg>" | an in-progress
 * stage string ("calling get_quote..."). Anything that isn't "ok" or an
 * "error"-prefixed string counts as still active. */
function cellState(cell) {
  if (!cell || cell === "pending") return "active";
  if (cell === "ok") return "done";
  if (cell.startsWith("error")) return "error";
  return "active"; // a live stage description
}

/** Maps live job state to the small AgentGraph diagram for ONE company (the
 * common single-company case - the diagram is decorative for multi-company
 * runs, which use the full SpecialistGrid table instead). */
export function deriveAgentGraph(routing, specialistStatus, ticker) {
  const companies = routing?.companies_identified || [];
  const company = ticker ? companies.find((c) => c.ticker === ticker) : companies[0];

  if (!routing || !company) {
    return { plannerStatus: "active", nodes: SPECIALISTS.map((s) => ({ ...s, status: "idle" })) };
  }

  const selected = new Set((company.specialists || []).filter((s) => s.selected).map((s) => s.specialist));
  const cellStatus = (specialistStatus || {})[company.ticker] || {};

  const nodes = SPECIALISTS.map((s) => {
    if (!selected.has(s.id)) return { ...s, status: "skipped" };
    return { ...s, status: cellState(cellStatus[s.id]) };
  });

  return { plannerStatus: "done", nodes, ticker: company.ticker };
}
