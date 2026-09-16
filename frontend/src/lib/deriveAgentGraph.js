import { parseRoutingTrace } from "./parseRoutingTrace";

const SPECIALISTS = [
  { id: "market_data", label: "Market Data", sub: "yfinance" },
  { id: "news_sentiment", label: "News + Sentiment", sub: "Tavily · Gemini" },
  { id: "filings", label: "Filings RAG", sub: "pgvector" },
];

/** Maps live job state to the small AgentGraph diagram for ONE company (the
 * common single-company case - the diagram is decorative for multi-company
 * runs, which use the full SpecialistGrid table instead). */
export function deriveAgentGraph(routingTrace, specialistStatus, ticker) {
  const parsed = parseRoutingTrace(routingTrace);
  const company = ticker
    ? parsed?.companies.find((c) => c.ticker === ticker)
    : parsed?.companies[0];

  if (!parsed || !company) {
    return { plannerStatus: "active", nodes: SPECIALISTS.map((s) => ({ ...s, status: "idle" })) };
  }

  const selected = new Set((company.selected || []).map((s) => s.specialist));
  const cellStatus = (specialistStatus || {})[company.ticker] || {};

  const nodes = SPECIALISTS.map((s) => {
    if (!selected.has(s.id)) return { ...s, status: "skipped" };
    const cell = cellStatus[s.id];
    const status = !cell || cell === "pending" ? "active" : cell === "ok" ? "done" : "error";
    return { ...s, status };
  });

  return { plannerStatus: "done", nodes, ticker: company.ticker };
}
