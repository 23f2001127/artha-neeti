import { friendlyStage } from "../../lib/stages";

function kindOf(status) {
  if (status === "ok") return "ok";
  if (typeof status === "string" && status.startsWith("error")) return "error";
  return "pending";
}

const DOT = {
  pending: "var(--color-running)",
  ok: "var(--color-ok)",
  error: "var(--color-error)",
};

/** A specialist's live status: "pending", "ok", "error: ...", or a stage string. */
export default function StatusBadge({ status }) {
  const kind = kindOf(status);
  const label = kind === "ok" ? "Complete" : kind === "error" ? "Unavailable" : friendlyStage(status);
  return (
    <span className="inline-flex items-center gap-2 text-[13px] text-[var(--color-ink-muted)]">
      <span className={`h-2 w-2 rounded-full ${kind === "pending" ? "pulse-dot" : ""}`} style={{ background: DOT[kind] }} />
      {label}
    </span>
  );
}
