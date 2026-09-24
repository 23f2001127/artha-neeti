import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import AgentGraph from "../../components/agent-graph/AgentGraph";
import { deriveAgentGraph } from "../../components/agent-graph/deriveAgentGraph";
import RoutingPanel from "./RoutingPanel";
import SpecialistGrid from "./SpecialistGrid";
import TimeGauge from "./TimeGauge";

/** Elapsed since the job actually started (server created_at), not since this
 * component mounted - a refresh or a shared job link must not reset the clock,
 * since the real ETA below is computed against this same elapsed time. */
function useElapsed(createdAt) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!createdAt) return 0;
  return Math.max(0, Math.round((now - new Date(createdAt).getTime()) / 1000));
}

function fmtElapsed(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** A real ETA string, or an honest "no estimate yet" - never a hardcoded
 * guess. estimated_duration_seconds is the historical average (same routing
 * mode) computed server-side the moment routing lands (see app/jobs.py). */
function etaLabel(job, elapsed) {
  const est = job?.estimated_duration_seconds;
  if (est == null) {
    return job?.routing
      ? "no ETA yet — not enough completed runs of this kind to estimate from"
      : null;
  }
  const remaining = Math.round(est - elapsed);
  const samples = job.estimated_duration_samples;
  const basis = `based on ${samples} past run${samples === 1 ? "" : "s"} of this kind`;
  if (remaining <= 5) return `wrapping up any moment — ${basis}`;
  return `~${fmtElapsed(remaining)} remaining — ${basis}`;
}

/** Same "wrapping up" threshold etaLabel() uses, for TimeGauge's color. */
function isWrappingUp(job, elapsed) {
  const est = job?.estimated_duration_seconds;
  return est != null && est - elapsed <= 5;
}

function phaseLabel(job) {
  if (!job) return "Submitting…";
  if (job.status === "queued") return "Queued";
  const cells = Object.values(job.specialist_status || {}).flatMap((per) => Object.values(per));
  if (!job.routing) return "Resolving companies and choosing specialists…";
  if (cells.length === 0) return "Dispatching specialists…";
  const inFlight = cells.filter((c) => c !== "ok" && !(typeof c === "string" && c.startsWith("error"))).length;
  if (inFlight > 0) return `Running specialists — ${cells.length - inFlight} of ${cells.length} done`;
  return "Reconciling specialist findings into a report…";
}

const fadeUp = {
  hidden: { opacity: 0, y: 14 },
  show: (i = 0) => ({ opacity: 1, y: 0, transition: { duration: 0.4, ease: "easeOut", delay: i * 0.08 } }),
};

export default function ProgressView({ job, pollError, onNewQuery }) {
  const elapsed = useElapsed(job?.created_at);
  const eta = etaLabel(job, elapsed);

  const companyCount = useMemo(() => {
    const fromStatus = Object.keys(job?.specialist_status || {}).length;
    if (fromStatus) return fromStatus;
    return job?.routing?.companies_identified?.length || 0;
  }, [job?.specialist_status, job?.routing]);

  const graph = useMemo(
    () => (companyCount <= 1 ? deriveAgentGraph(job?.routing, job?.specialist_status) : null),
    [companyCount, job?.routing, job?.specialist_status],
  );

  return (
    <div className="mx-auto max-w-[860px] px-6 pt-10 pb-20">
      <motion.div variants={fadeUp} initial="hidden" animate="show" custom={0} className="flex items-start justify-between gap-4 mb-6">
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
      </motion.div>

      <motion.div variants={fadeUp} initial="hidden" animate="show" custom={1} className="flex items-center gap-4 mb-6">
        <TimeGauge
          elapsed={elapsed}
          estimatedDuration={job?.estimated_duration_seconds}
          wrappingUp={isWrappingUp(job, elapsed)}
        />
        <div className="flex flex-col gap-1.5">
          <span className="inline-flex items-center gap-2 self-start text-[13px] font-medium text-[var(--color-running)] bg-[var(--color-running-tint)] px-3 py-1.5 rounded-full">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-running)] pulse-dot pulse-glow" />
            {phaseLabel(job)}
          </span>
          {eta && <span className="text-[11.5px] text-[var(--color-ink-faint)]">{eta}</span>}
        </div>
      </motion.div>

      {pollError && (
        <p className="mb-4 text-[13px] text-[var(--color-error)] bg-[var(--color-error-tint)] rounded-[var(--radius-sm)] px-3 py-2">
          {pollError} — still retrying.
        </p>
      )}

      {graph && (
        <motion.div
          variants={fadeUp}
          initial="hidden"
          animate="show"
          custom={1.5}
          className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] px-6 py-5 mb-5"
        >
          <AgentGraph nodes={graph.nodes} plannerStatus={graph.plannerStatus} height={170} />
        </motion.div>
      )}

      <motion.div variants={fadeUp} initial="hidden" animate="show" custom={2} className="space-y-5">
        <RoutingPanel routing={job?.routing} routingTrace={job?.routing_trace} />
        <SpecialistGrid specialistStatus={job?.specialist_status} />
      </motion.div>
    </div>
  );
}
