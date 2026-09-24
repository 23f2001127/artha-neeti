import { useReducedMotion } from "../../hooks/useReducedMotion";

const STATUS_COLOR = {
  idle: "var(--color-border-strong)",
  active: "var(--color-running)",
  done: "var(--color-ok)",
  error: "var(--color-error)",
  skipped: "var(--color-skip)",
};

const WIDTH = 600;
const HEIGHT = 280;
const CENTER_Y = 134;
const PLANNER = { x: 72, y: CENTER_Y, r: 26 };
const REPORT = { x: WIDTH - 72, y: CENTER_Y, r: 24 };
const SPEC_X = WIDTH / 2;
const SPEC_R = 19;

function slotYs(count) {
  // 90px apart leaves ~20px between one node's subtitle and the next node.
  if (count === 1) return [CENTER_Y];
  if (count === 2) return [CENTER_Y - 45, CENTER_Y + 45];
  return [CENTER_Y - 90, CENTER_Y, CENTER_Y + 90];
}

function curve(x1, y1, x2, y2) {
  const dx = (x2 - x1) * 0.55;
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function Electrons({ path, count, duration, color }) {
  return Array.from({ length: count }, (_, i) => (
    <circle key={i} r="3" fill={color} className="electron" style={{ "--glow": color }}>
      <animateMotion dur={`${duration}s`} begin={`${(i * duration) / count}s`} repeatCount="indefinite" path={path} />
    </circle>
  ));
}

function Edge({ path, status, reducedMotion }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.idle;
  const lit = status === "active" || status === "done";
  return (
    <g>
      <path
        d={path}
        fill="none"
        stroke={lit || status === "error" ? color : "var(--color-border)"}
        strokeWidth={lit ? 1.8 : 1.4}
        strokeDasharray={status === "skipped" ? "3 5" : undefined}
        opacity={status === "done" ? 0.55 : 1}
      />
      {!reducedMotion && status === "active" && (
        <Electrons path={path} count={3} duration={1.3} color="var(--color-brand)" />
      )}
      {!reducedMotion && status === "done" && (
        <Electrons path={path} count={2} duration={2.6} color="var(--color-brand)" />
      )}
    </g>
  );
}

function Node({ x, y, r, label, sub, status, labelPosition = "below" }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.idle;
  const dim = status === "idle" || status === "skipped";
  const labelY = labelPosition === "below" ? y + r + 17 : y - r - 22;
  return (
    <g opacity={status === "skipped" ? 0.6 : 1}>
      {status === "active" && (
        <circle cx={x} cy={y} r={r} fill="none" stroke={color} strokeWidth="1.5" className="node-pulse" />
      )}
      <circle cx={x} cy={y} r={r} fill="var(--color-surface)" stroke={color} strokeWidth="1.8" />
      <circle cx={x} cy={y} r={r * 0.34} fill={color} opacity={dim ? 0.5 : 1} />
      <text x={x} y={labelY} textAnchor="middle" style={{ fontSize: 12, fontWeight: 600, fill: "var(--color-ink)" }}>
        {label}
      </text>
      {sub && (
        <text x={x} y={labelY + 14} textAnchor="middle" style={{ fontSize: 10.5, fill: "var(--color-ink-faint)" }}>
          {sub}
        </text>
      )}
    </g>
  );
}

/**
 * Planner -> specialists -> report pipeline. `nodes` are the specialists
 * ({ id, label, sub, status }); statuses are idle | active | done | error |
 * skipped.
 */
export default function AgentGraph({ nodes, plannerStatus = "idle", reportStatus = "idle" }) {
  const reducedMotion = useReducedMotion();
  const ys = slotYs(nodes.length);

  const inbound = nodes.map((n, i) => ({
    id: n.id,
    path: curve(PLANNER.x + PLANNER.r, PLANNER.y, SPEC_X - SPEC_R, ys[i]),
    status: n.status,
  }));
  const outbound = nodes.map((n, i) => ({
    id: n.id,
    path: curve(SPEC_X + SPEC_R, ys[i], REPORT.x - REPORT.r, REPORT.y),
    status: n.status === "done" ? (reportStatus === "idle" ? "done" : reportStatus) : n.status === "skipped" ? "skipped" : "idle",
  }));

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto" role="img" aria-label="Research pipeline status">
      {inbound.map((e) => (
        <Edge key={`in-${e.id}`} path={e.path} status={e.status} reducedMotion={reducedMotion} />
      ))}
      {outbound.map((e) => (
        <Edge key={`out-${e.id}`} path={e.path} status={e.status} reducedMotion={reducedMotion} />
      ))}
      <Node {...PLANNER} label="Planner" sub="routes the question" status={plannerStatus} />
      {nodes.map((n, i) => (
        <Node key={n.id} x={SPEC_X} y={ys[i]} r={SPEC_R} label={n.label} sub={n.sub} status={n.status} />
      ))}
      <Node {...REPORT} label="Report" sub="synthesis" status={reportStatus} />
    </svg>
  );
}
