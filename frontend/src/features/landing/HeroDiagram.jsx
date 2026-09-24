import { useEffect, useState } from "react";
import AgentGraph from "../../components/agent-graph/AgentGraph";
import { SPECIALISTS } from "../../components/agent-graph/deriveAgentGraph";

const FRAMES = [
  { planner: "active", specialists: ["idle", "idle", "idle"], report: "idle" },
  { planner: "done", specialists: ["active", "active", "idle"], report: "idle" },
  { planner: "done", specialists: ["done", "active", "active"], report: "idle" },
  { planner: "done", specialists: ["done", "done", "active"], report: "idle" },
  { planner: "done", specialists: ["done", "done", "done"], report: "active" },
  { planner: "done", specialists: ["done", "done", "done"], report: "done" },
  { planner: "done", specialists: ["done", "done", "done"], report: "done" },
];
const FRAME_MS = 1400;

export default function HeroDiagram() {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % FRAMES.length), FRAME_MS);
    return () => clearInterval(id);
  }, []);

  const current = FRAMES[frame];
  const nodes = SPECIALISTS.map((s, i) => ({ ...s, status: current.specialists[i] }));
  return <AgentGraph nodes={nodes} plannerStatus={current.planner} reportStatus={current.report} />;
}
