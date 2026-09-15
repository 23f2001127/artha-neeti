const SPECIALIST_LABEL = {
  market_data: "Market Data",
  news_sentiment: "News & Sentiment",
  filings: "Filings",
};

/** cell status as stored by the backend: "pending" | "ok" | "error: <msg>" */
export function specialistLabel(key) {
  return SPECIALIST_LABEL[key] || key;
}

export default function StatusBadge({ status, compact = false }) {
  if (!status || status === "pending") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-running)]">
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-running)] pulse-dot" />
        {!compact && "running"}
      </span>
    );
  }
  if (status === "ok") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-ok)]">
        <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-ok)]" />
        {!compact && "done"}
      </span>
    );
  }
  const detail = status.startsWith("error:") ? status.slice(6).trim() : status;
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-error)]" title={detail}>
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-error)]" />
      {!compact && "failed"}
    </span>
  );
}
