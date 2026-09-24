export const SPECIALISTS = [
  { id: "market_data", label: "Market data", sub: "prices, ratios, trends" },
  { id: "news_sentiment", label: "News & sentiment", sub: "recent coverage" },
  { id: "filings", label: "Annual report", sub: "filings analysis" },
];

/** A status cell is "pending" | "ok" | "error: <msg>" | a live stage string. */
function cellState(cell) {
  if (!cell || cell === "pending") return "active";
  if (cell === "ok") return "done";
  if (cell.startsWith("error")) return "error";
  return "active";
}

/** Maps live job state to the pipeline diagram for one company. */
export function deriveAgentGraph(routing, specialistStatus, ticker) {
  const companies = routing?.companies_identified || [];
  const company = ticker ? companies.find((c) => c.ticker === ticker) : companies[0];

  if (!routing || !company) {
    return {
      plannerStatus: "active",
      reportStatus: "idle",
      nodes: SPECIALISTS.map((s) => ({ ...s, status: "idle" })),
    };
  }

  const selected = new Set((company.specialists || []).filter((s) => s.selected).map((s) => s.specialist));
  const cellStatus = (specialistStatus || {})[company.ticker] || {};
  const nodes = SPECIALISTS.map((s) =>
    selected.has(s.id) ? { ...s, status: cellState(cellStatus[s.id]) } : { ...s, status: "skipped" },
  );
  const running = nodes.some((n) => n.status === "active");

  return {
    plannerStatus: "done",
    reportStatus: running ? "idle" : "active",
    nodes,
    ticker: company.ticker,
  };
}
