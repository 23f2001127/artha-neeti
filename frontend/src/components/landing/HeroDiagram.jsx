import { useEffect, useState } from "react";
import AgentGraph from "../common/AgentGraph";

const BASE = [
  { id: "market_data", label: "Market Data", sub: "yfinance" },
  { id: "news_sentiment", label: "News + Sentiment", sub: "Tavily · Gemini" },
  { id: "filings", label: "Filings RAG", sub: "pgvector" },
];

// A self-running demo loop for the hero: route -> dispatch one specialist at a
// time -> all done -> reset. Purely illustrative (the real, data-driven version
// of this diagram lives in the progress view).
const SEQUENCE = [
  { planner: "active", statuses: ["idle", "idle", "idle"] },
  { planner: "done", statuses: ["active", "idle", "idle"] },
  { planner: "done", statuses: ["done", "active", "idle"] },
  { planner: "done", statuses: ["done", "done", "active"] },
  { planner: "done", statuses: ["done", "done", "done"] },
];
const STEP_MS = 1100;

export default function HeroDiagram() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setStep((s) => (s + 1) % (SEQUENCE.length + 2)); // +2 = a brief pause on the all-done frame
    }, STEP_MS);
    return () => clearInterval(id);
  }, []);

  const frame = SEQUENCE[Math.min(step, SEQUENCE.length - 1)];
  const nodes = BASE.map((n, i) => ({ ...n, status: frame.statuses[i] }));

  return <AgentGraph nodes={nodes} plannerStatus={frame.planner} height={210} />;
}
