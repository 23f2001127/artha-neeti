import { useEffect, useMemo, useState } from "react";
import AgentGraph from "../../components/agent-graph/AgentGraph";
import { deriveAgentGraph } from "../../components/agent-graph/deriveAgentGraph";
import RoutingPanel from "./RoutingPanel";
import SpecialistGrid from "./SpecialistGrid";
import TimeGauge from "./TimeGauge";

/** Seconds since the job was created server-side, so a refresh keeps the clock. */
function useElapsed(createdAt) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  if (!createdAt) return 0;
  return Math.max(0, Math.round((now - new Date(createdAt).getTime()) / 1000));
}

function remainingLabel(job, elapsed) {
  const est = job?.estimated_duration_seconds;
  if (est == null) return { primary: "Estimating time", secondary: job?.routing ? "Not enough past reports of this kind yet" : null };
  const remaining = Math.round(est - elapsed);
  const samples = job.estimated_duration_samples;
  const secondary = `Based on ${samples} recent report${samples === 1 ? "" : "s"} like this one`;
  if (remaining <= 10) return { primary: "Almost done", secondary };
  const minutes = Math.ceil(remaining / 60);
  return { primary: `About ${minutes} min remaining`, secondary };
}

function phaseLabel(job) {
  if (!job || job.status === "queued") return "Starting";
  if (!job.routing) return "Planning the research";
  const cells = Object.values(job.specialist_status || {}).flatMap((per) => Object.values(per));
  if (!cells.length) return "Dispatching sources";
  const done = cells.filter((c) => c === "ok" || (typeof c === "string" && c.startsWith("error"))).length;
  if (done < cells.length) return `Gathering data · ${done} of ${cells.length} sources complete`;
  return "Writing the report";
}

export default function ProgressView({ job, pollError, onNewQuery }) {
  const elapsed = useElapsed(job?.created_at);
  const eta = remainingLabel(job, elapsed);
  const companies = job?.routing?.companies_identified || [];
  const tickers = Object.keys(job?.specialist_status || {});
  const [selected, setSelected] = useState(null);
  const activeTicker = selected || tickers[0] || companies[0]?.ticker;
  const names = Object.fromEntries(companies.map((c) => [c.ticker, c.name]));

  const graph = useMemo(
    () => deriveAgentGraph(job?.routing, job?.specialist_status, activeTicker),
    [job?.routing, job?.specialist_status, activeTicker],
  );
  const wrappingUp = job?.estimated_duration_seconds != null && job.estimated_duration_seconds - elapsed <= 10;

  return (
    <div className="pb-20">
      <section className="border-b border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
        <div className="page py-8 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6 fade-up">
          <div className="min-w-0">
            <p className="inline-flex items-center gap-2 text-[12.5px] font-semibold uppercase tracking-[0.08em] text-[var(--color-brand)]">
              <span className="h-2 w-2 rounded-full bg-[var(--color-running)] pulse-glow" />
              Research in progress
            </p>
            <h1 className="font-display mt-2 text-[26px] sm:text-[32px] leading-tight font-semibold text-[var(--color-ink)] max-w-[900px]">
              {job?.query || "Preparing your research…"}
            </h1>
            <p className="mt-3 text-[14.5px] text-[var(--color-ink-muted)]">{phaseLabel(job)}</p>
          </div>
          <div className="flex items-center gap-5 shrink-0">
            <TimeGauge elapsed={elapsed} estimatedDuration={job?.estimated_duration_seconds} wrappingUp={wrappingUp} />
            <div>
              <p className="text-[15px] font-semibold text-[var(--color-ink)]">{eta.primary}</p>
              {eta.secondary && <p className="mt-0.5 text-[12.5px] text-[var(--color-ink-faint)] max-w-[220px]">{eta.secondary}</p>}
              <button
                onClick={onNewQuery}
                className="mt-3 h-9 px-3.5 text-[13px] font-medium rounded-[var(--radius-sm)] border border-[var(--color-border-strong)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)] transition-colors cursor-pointer"
              >
                Start a different report
              </button>
            </div>
          </div>
        </div>
      </section>

      {pollError && (
        <div className="page pt-6">
          <p className="rounded-[var(--radius-md)] bg-[var(--color-error-tint)] px-4 py-3 text-[13.5px] text-[var(--color-ink)]">
            {pollError} Retrying automatically.
          </p>
        </div>
      )}

      <div className="page pt-8 grid grid-cols-1 xl:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)] gap-4 items-start">
        <div className="space-y-4 min-w-0 fade-up" style={{ animationDelay: "60ms" }}>
          <section className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-5">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
              <div>
                <h3 className="text-[14.5px] font-semibold text-[var(--color-ink)]">Live pipeline</h3>
                <p className="text-[12.5px] text-[var(--color-ink-faint)]">
                  {activeTicker ? `${names[activeTicker] || activeTicker}` : "Planning the research"}
                </p>
              </div>
              {tickers.length > 1 && (
                <div className="inline-flex rounded-[var(--radius-sm)] bg-[var(--color-surface-sunken)] p-0.5">
                  {tickers.map((t) => (
                    <button
                      key={t}
                      onClick={() => setSelected(t)}
                      className={`px-3 py-1 text-[12.5px] font-medium rounded-[5px] transition-colors cursor-pointer ${
                        t === activeTicker
                          ? "bg-[var(--color-surface-muted)] text-[var(--color-ink)]"
                          : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <AgentGraph nodes={graph.nodes} plannerStatus={graph.plannerStatus} reportStatus={graph.reportStatus} />
          </section>
          <SpecialistGrid specialistStatus={job?.specialist_status} names={names} />
        </div>
        <div className="min-w-0 fade-up" style={{ animationDelay: "120ms" }}>
          <RoutingPanel routing={job?.routing} />
        </div>
      </div>
    </div>
  );
}
