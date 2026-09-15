import { useEffect, useState } from "react";
import RoutingPanel from "./RoutingPanel";
import SpecialistGrid from "./SpecialistGrid";

function useElapsed(startedAt) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!startedAt) return 0;
  return Math.max(0, Math.round((now - startedAt) / 1000));
}

function fmtElapsed(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function phaseLabel(job) {
  if (!job) return "Submitting…";
  if (job.status === "queued") return "Queued";
  const cells = Object.values(job.specialist_status || {}).flatMap((per) => Object.values(per));
  if (!job.routing_trace) return "Resolving companies and choosing specialists…";
  if (cells.length === 0) return "Dispatching specialists…";
  const inFlight = cells.filter((c) => c === "pending").length;
  if (inFlight > 0) return `Running specialists — ${cells.length - inFlight} of ${cells.length} done`;
  return "Reconciling specialist findings into a report…";
}

export default function ProgressView({ job, pollError, onNewQuery }) {
  const [startedAt] = useState(() => Date.now());
  const elapsed = useElapsed(startedAt);

  return (
    <div className="mx-auto max-w-[860px] px-6 pt-10 pb-20">
      <div className="flex items-start justify-between gap-4 mb-6 fade-up">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-[var(--color-ink-faint)] mb-1">Research query</p>
          <h1 className="text-[19px] font-semibold text-[var(--color-ink)] leading-snug max-w-[560px]">
            {job?.query || "…"}
          </h1>
        </div>
        <button
          onClick={onNewQuery}
          className="shrink-0 text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-brand)] border border-[var(--color-border)] rounded-[var(--radius-sm)] px-3 py-1.5 transition-colors cursor-pointer"
        >
          Cancel / new query
        </button>
      </div>

      <div className="flex items-center gap-3 mb-6 fade-up">
        <span className="inline-flex items-center gap-2 text-[13px] font-medium text-[var(--color-running)] bg-[var(--color-running-tint)] px-3 py-1.5 rounded-full">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-running)] pulse-dot" />
          {phaseLabel(job)}
        </span>
        <span className="mono text-[12px] text-[var(--color-ink-faint)]">{fmtElapsed(elapsed)} elapsed</span>
        <span className="text-[11.5px] text-[var(--color-ink-faint)]">
          — typically a few minutes; multi-company comparisons take longer
        </span>
      </div>

      {pollError && (
        <p className="mb-4 text-[13px] text-[var(--color-error)] bg-[var(--color-error-tint)] rounded-[var(--radius-sm)] px-3 py-2">
          {pollError} — still retrying.
        </p>
      )}

      <div className="space-y-5">
        <RoutingPanel routingTrace={job?.routing_trace} />
        <SpecialistGrid specialistStatus={job?.specialist_status} />
      </div>
    </div>
  );
}
