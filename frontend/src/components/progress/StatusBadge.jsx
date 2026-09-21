import { motion } from "framer-motion";

const SPECIALIST_LABEL = {
  market_data: "Market Data",
  news_sentiment: "News & Sentiment",
  filings: "Filings",
};

/** cell status as stored by the backend: "pending" | "ok" | "error: <msg>" |
 * an in-progress stage string, e.g. "calling get_quote...", "thinking..." */
export function specialistLabel(key) {
  return SPECIALIST_LABEL[key] || key;
}

function kindOf(status) {
  if (!status || status === "ok") return status === "ok" ? "ok" : "pending";
  if (typeof status === "string" && status.startsWith("error")) return "error";
  return "pending"; // any other string is a live stage description - still in progress
}

const CONFIG = {
  pending: { color: "var(--color-running)", label: "running" },
  ok: { color: "var(--color-ok)", label: "done" },
  error: { color: "var(--color-error)", label: "failed" },
};

export default function StatusBadge({ status, compact = false }) {
  const kind = kindOf(status);
  const { color, label: fallbackLabel } = CONFIG[kind];
  const detail = kind === "error" && status.startsWith("error:") ? status.slice(6).trim() : status;
  // A pending cell whose status is more than the bare seed value ("pending")
  // is carrying a live stage description - show that instead of just "running".
  const label = kind === "pending" && status && status !== "pending" ? status : fallbackLabel;

  // Neither AnimatePresence's exit nor a from-zero entrance animate()
  // reliably completes with this framer-motion/React 19 pairing (confirmed
  // live) once the parent re-renders frequently, which is exactly this
  // component's situation during active polling: a badge could freeze mid-
  // transition (invisible) or old values could stack in the DOM forever.
  // initial={false} skips the animated entrance and renders at the final
  // state immediately - live status must always be visible, so correctness
  // wins over the pop-in bounce. Plain key-based remount (no AnimatePresence)
  // still unmounts the old badge correctly.
  return (
    <motion.span
      key={status || kind}
      title={kind === "error" ? detail : undefined}
      className="inline-flex items-center gap-1.5 text-[12px]"
      style={{ color }}
      initial={false}
      animate={{ opacity: 1, scale: 1 }}
    >
      {kind === "pending" ? (
        <span className="h-1.5 w-1.5 rounded-full pulse-dot" style={{ backgroundColor: color }} />
      ) : (
        <motion.span
          className="h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: color }}
          initial={false}
          animate={{ scale: 1 }}
        />
      )}
      {!compact && label}
    </motion.span>
  );
}
