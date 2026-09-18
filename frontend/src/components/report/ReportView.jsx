import { useState } from "react";
import RoutingPanel from "../progress/RoutingPanel";
import CompanyReportCard from "./CompanyReportCard";
import ComparisonView from "./ComparisonView";

function CopyLinkButton() {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(window.location.href);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-brand)] border border-[var(--color-border)] rounded-[var(--radius-sm)] px-3 py-1.5 transition-colors cursor-pointer"
    >
      {copied ? "Link copied" : "Copy link"}
    </button>
  );
}

export default function ReportView({ job, onNewQuery }) {
  const [showRouting, setShowRouting] = useState(false);
  const report = job.report;

  // Total failure: the job itself errored and there is no usable report.
  if (job.status === "error" && !report) {
    return (
      <div className="mx-auto max-w-[720px] px-6 pt-16">
        <p className="text-[11px] uppercase tracking-wide text-[var(--color-ink-faint)] mb-1">Research query</p>
        <h1 className="text-[19px] font-semibold text-[var(--color-ink)] mb-4">{job.query}</h1>
        <div className="rounded-[var(--radius-md)] border border-[var(--color-error-tint)] bg-[var(--color-error-tint)] px-4 py-3 mb-4">
          <p className="text-[13.5px] text-[var(--color-error)]">{job.error || "The run failed."}</p>
        </div>
        {job.routing && <RoutingPanel routing={job.routing} routingTrace={job.routing_trace} />}
        <button
          onClick={onNewQuery}
          className="mt-6 text-[13px] font-medium px-4 py-1.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-bg)] hover:bg-[var(--color-brand-soft)] transition-colors cursor-pointer"
        >
          Try another query
        </button>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mx-auto max-w-[720px] px-6 pt-16">
        <p className="text-[13px] text-[var(--color-ink-muted)]">No report available for this job.</p>
      </div>
    );
  }

  const tickers = Object.keys(report.reports || {});
  const isMulti = report.mode === "multi";
  const isNone = report.mode === "none";

  return (
    <div className="mx-auto max-w-[860px] px-6 pt-10 pb-24">
      <div className="flex items-start justify-between gap-4 mb-2 fade-up">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-[var(--color-ink-faint)] mb-1">Research query</p>
          <h1 className="text-[19px] font-semibold text-[var(--color-ink)] leading-snug max-w-[600px]">
            {report.query || job.query}
          </h1>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <CopyLinkButton />
          <button
            onClick={onNewQuery}
            className="text-[12px] font-medium text-[var(--color-bg)] bg-[var(--color-brand)] hover:bg-[var(--color-brand-soft)] rounded-[var(--radius-sm)] px-3 py-1.5 transition-colors cursor-pointer"
          >
            New query
          </button>
        </div>
      </div>

      <div className="mb-6 fade-up">
        <button
          onClick={() => setShowRouting((v) => !v)}
          className="text-[11.5px] text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)] underline decoration-dotted cursor-pointer"
        >
          {showRouting ? "Hide" : "How was this routed?"}
        </button>
        {showRouting && (
          <div className="mt-3">
            <RoutingPanel routing={report.routing} routingTrace={report.routing_trace} />
          </div>
        )}
      </div>

      {isNone && (
        <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface-muted)] px-4 py-3">
          <p className="text-[13.5px] text-[var(--color-ink-muted)]">
            {report.note || "No company could be resolved for this query."}
          </p>
        </div>
      )}

      {!isNone && isMulti && (
        <div className="space-y-8">
          <ComparisonView comparison={report.comparison} />
          <div>
            <h2 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink)] mb-4">
              Per-company reports
            </h2>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {tickers.map((t) => (
                <div
                  key={t}
                  className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-5"
                >
                  <CompanyReportCard ticker={t} report={report.reports[t]} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!isNone && !isMulti && tickers.length > 0 && (
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] shadow-[var(--shadow-card)] p-6 fade-up">
          <CompanyReportCard ticker={tickers[0]} report={report.reports[tickers[0]]} heading={false} />
        </div>
      )}
    </div>
  );
}
