import { motion } from "framer-motion";

const STATUS_COLOR = {
  idle: "var(--color-ink-faint)",
  active: "var(--color-running)",
  done: "var(--color-brand)",
  error: "var(--color-error)",
  skipped: "var(--color-skip)",
};

function Node({ x, y, r, label, sub, status }) {
  const color = STATUS_COLOR[status] || STATUS_COLOR.idle;
  return (
    <g>
      {status === "active" && (
        <motion.circle
          cx={x}
          cy={y}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          initial={{ opacity: 0.6, scale: 1 }}
          animate={{ opacity: 0, scale: 1.9 }}
          transition={{ duration: 1.4, repeat: Infinity, ease: "easeOut" }}
          style={{ transformOrigin: `${x}px ${y}px` }}
        />
      )}
      <motion.circle
        cx={x}
        cy={y}
        r={r}
        fill="var(--color-surface)"
        stroke={color}
        strokeWidth="1.6"
        animate={{ stroke: color }}
        transition={{ duration: 0.4 }}
      />
      <motion.circle
        cx={x}
        cy={y}
        r={r * 0.32}
        fill={color}
        animate={{ fill: color, opacity: status === "idle" ? 0.4 : 1 }}
        transition={{ duration: 0.4 }}
      />
      <text
        x={x}
        y={y + r + 16}
        textAnchor="middle"
        className="mono"
        style={{ fontSize: 10, fill: "var(--color-ink)", fontWeight: 500 }}
      >
        {label}
      </text>
      {sub && (
        <text x={x} y={y + r + 29} textAnchor="middle" style={{ fontSize: 8.5, fill: "var(--color-ink-faint)" }}>
          {sub}
        </text>
      )}
    </g>
  );
}

function Edge({ x1, y1, x2, y2, status }) {
  const active = status === "active" || status === "done";
  const color = STATUS_COLOR[status] || STATUS_COLOR.idle;
  const dx = (x2 - x1) * 0.5;
  const path = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  return (
    <>
      <path d={path} fill="none" stroke="var(--color-border)" strokeWidth="1.5" />
      {active && (
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          className={status === "active" ? "flow-line" : ""}
          opacity={status === "active" ? 0.9 : 0.5}
        />
      )}
    </>
  );
}

/**
 * A small SVG diagram of the real pipeline shape: Planner -> up to 3
 * specialists. `nodes` = [{id,label,sub,status}] for market_data /
 * news_sentiment / filings (status: idle|active|done|error|skipped).
 * `plannerStatus` colors the hub node the same way.
 */
// Room reserved below the lowest node's center for its two-line label (name +
// sub). Proportional slot positions (rather than fixed-pixel margins) keep
// this correct at any `height` the caller passes; the 3-node case is the tight
// one since its bottom slot sits closest to the edge.
const LABEL_ROOM = 34;

export default function AgentGraph({ nodes, plannerStatus = "idle", height = 190 }) {
  const width = 420;
  const viewH = nodes.length >= 3 ? height + LABEL_ROOM : height;
  const hub = { x: 62, y: height / 2 };
  const slotY =
    nodes.length === 1
      ? [height / 2]
      : nodes.length === 2
        ? [height * 0.28, height * 0.72]
        : [height * 0.14, height / 2, height * 0.86];
  const nx = width - 78;

  return (
    <svg viewBox={`0 0 ${width} ${viewH}`} className="w-full h-auto" role="img" aria-label="Agent pipeline status">
      {nodes.map((n, i) => (
        <Edge key={n.id} x1={hub.x + 20} y1={hub.y} x2={nx - 20} y2={slotY[i]} status={n.status} />
      ))}
      <Node x={hub.x} y={hub.y} r={20} label="Planner" status={plannerStatus} />
      {nodes.map((n, i) => (
        <Node key={n.id} x={nx} y={slotY[i]} r={16} label={n.label} sub={n.sub} status={n.status} />
      ))}
    </svg>
  );
}
