import { AnimatePresence, motion } from "framer-motion";

const SPECIALIST_LABEL = {
  market_data: "Market Data",
  news_sentiment: "News & Sentiment",
  filings: "Filings",
};

/** cell status as stored by the backend: "pending" | "ok" | "error: <msg>" */
export function specialistLabel(key) {
  return SPECIALIST_LABEL[key] || key;
}

function kindOf(status) {
  if (!status || status === "pending") return "pending";
  if (status === "ok") return "ok";
  return "error";
}

const CONFIG = {
  pending: { color: "var(--color-running)", label: "running" },
  ok: { color: "var(--color-ok)", label: "done" },
  error: { color: "var(--color-error)", label: "failed" },
};

export default function StatusBadge({ status, compact = false }) {
  const kind = kindOf(status);
  const { color, label } = CONFIG[kind];
  const detail = kind === "error" && status.startsWith("error:") ? status.slice(6).trim() : status;

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={kind}
        title={kind === "error" ? detail : undefined}
        className="inline-flex items-center gap-1.5 text-[12px]"
        style={{ color }}
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.8 }}
        transition={{ duration: 0.28, ease: [0.34, 1.56, 0.64, 1] }}
      >
        {kind === "pending" ? (
          <span className="h-1.5 w-1.5 rounded-full pulse-dot" style={{ backgroundColor: color }} />
        ) : (
          <motion.span
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: color }}
            initial={{ scale: 1.8 }}
            animate={{ scale: 1 }}
            transition={{ duration: 0.35 }}
          />
        )}
        {!compact && label}
      </motion.span>
    </AnimatePresence>
  );
}
