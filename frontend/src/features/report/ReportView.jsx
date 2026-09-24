import { useMemo, useState } from "react";
import RoutingPanel from "../progress/RoutingPanel";
import FollowUpDrawer from "../followup/FollowUpDrawer";
import CompanyDashboard from "./CompanyDashboard";
import ComparisonSection from "./ComparisonSection";
import PortfolioSection from "./PortfolioSection";
import ShareMenu from "./ShareMenu";
import { useVisuals } from "./useVisuals";
import { downloadReportPdf, ApiError } from "../../lib/api";
import { DownloadIcon, PlusIcon } from "../../components/ui/icons";
import { formatDate } from "../../lib/format";
import { readableReport } from "../../lib/prose";

function DownloadPdfButton({ jobId, tickers }) {
  const [state, setState] = useState("idle");
  async function download() {
    setState("working");
    try {
      const slug = tickers.map((t) => t.toLowerCase()).join("-") || "report";
      await downloadReportPdf(jobId, `arthaneeti-${slug}.pdf`);
      setState("idle");
    } catch (err) {
      setState(err instanceof ApiError ? "error" : "error");
      setTimeout(() => setState("idle"), 2500);
    }
  }
  return (
    <button
      onClick={download}
      disabled={state === "working"}
      className="inline-flex items-center gap-2 h-10 px-4 text-[13.5px] font-medium rounded-[var(--radius-sm)] border border-[var(--color-border-strong)] text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)] transition-colors disabled:opacity-60 cursor-pointer"
    >
      <DownloadIcon className="h-4 w-4" />
      {state === "working" ? "Preparing PDF…" : state === "error" ? "Download failed" : "Download PDF"}
    </button>
  );
}

function reportKind(report) {
  if (report.portfolio) return "Portfolio review";
  if (report.comparison) return "Company comparison";
  if (report.mode === "multi") return "Multi-company research";
  return "Company research";
}

function Tabs({ tabs, value, onChange }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-[var(--color-border)] mb-6" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`relative shrink-0 px-4 py-3 text-[14px] font-medium transition-colors cursor-pointer ${
            value === t.id ? "text-[var(--color-ink)]" : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
          }`}
        >
          {t.label}
          {value === t.id && <span className="absolute inset-x-3 -bottom-px h-[2px] rounded-full bg-[var(--color-brand)]" />}
        </button>
      ))}
    </div>
  );
}

function Notice({ title, body, onNewQuery }) {
  return (
    <div className="page py-16">
      <div className="max-w-[640px] rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-8">
        <h1 className="text-[20px] font-semibold text-[var(--color-ink)]">{title}</h1>
        <p className="mt-2 text-[14.5px] leading-relaxed text-[var(--color-ink-muted)]">{body}</p>
        <button
          onClick={onNewQuery}
          className="mt-6 h-10 px-5 text-[14px] font-semibold rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-on-brand)] hover:bg-[var(--color-brand-soft)] transition-colors cursor-pointer"
        >
          Start a new report
        </button>
      </div>
    </div>
  );
}

export default function ReportView({ job, onNewQuery, onOpenJob }) {
  const report = useMemo(() => readableReport(job.report), [job.report]);
  const { visuals, loading: chartsLoading } = useVisuals(job);
  const tickers = Object.keys(report?.reports || {});
  const isMulti = tickers.length > 1;
  const [tab, setTab] = useState(isMulti ? "overview" : tickers[0]);
  const [showMethod, setShowMethod] = useState(false);

  if (job.status === "error" && !report) {
    return (
      <Notice
        title="This report couldn't be completed"
        body="Something went wrong while the research was running. Please try again in a few minutes."
        onNewQuery={onNewQuery}
      />
    );
  }
  if (!report || report.mode === "none") {
    return (
      <Notice
        title="We couldn't identify a listed company"
        body="Try naming the company or its NSE ticker, for example “Give me a research view on Infosys” or “Compare TCS and Wipro”."
        onNewQuery={onNewQuery}
      />
    );
  }

  const companies = report.routing?.companies_identified || [];
  const nameFor = (t) => visuals?.companies?.[t]?.name || companies.find((c) => c.ticker === t)?.name || t;
  const title = report.query || job.query;
  const tabs = [
    { id: "overview", label: report.portfolio ? "Portfolio" : "Comparison" },
    ...tickers.map((t) => ({ id: t, label: nameFor(t) })),
  ];

  return (
    <div className="pb-28">
      <section className="border-b border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
        <div className="page py-8 flex flex-col lg:flex-row lg:items-end lg:justify-between gap-6">
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 text-[12.5px] text-[var(--color-ink-faint)]">
              <span className="font-semibold uppercase tracking-[0.08em] text-[var(--color-brand)]">{reportKind(report)}</span>
              <span>·</span>
              <span>{formatDate(job.updated_at || job.created_at)}</span>
            </p>
            <h1 className="font-display mt-2 text-[28px] sm:text-[34px] leading-tight font-semibold text-[var(--color-ink)] max-w-[900px]">
              {title}
            </h1>
            <div className="mt-4 flex flex-wrap gap-2">
              {tickers.map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-[13px] text-[var(--color-ink)]"
                >
                  {nameFor(t)}
                  <span className="mono text-[11.5px] text-[var(--color-ink-faint)]">{t}</span>
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <ShareMenu jobId={job.job_id} title={title} />
            <DownloadPdfButton jobId={job.job_id} tickers={tickers} />
            <button
              onClick={onNewQuery}
              className="inline-flex items-center gap-2 h-10 px-4 text-[13.5px] font-semibold rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-on-brand)] hover:bg-[var(--color-brand-soft)] transition-colors cursor-pointer"
            >
              <PlusIcon className="h-4 w-4" />
              New research
            </button>
          </div>
        </div>
      </section>

      <div className="page pt-8">
        {isMulti && <Tabs tabs={tabs} value={tab} onChange={setTab} />}

        {isMulti && tab === "overview" ? (
          report.portfolio ? (
            <PortfolioSection portfolio={report.portfolio} visuals={visuals} tickers={tickers} />
          ) : (
            <ComparisonSection comparison={report.comparison} visuals={visuals} tickers={tickers} />
          )
        ) : (
          <CompanyDashboard
            key={tab}
            ticker={tab}
            report={report.reports[tab]}
            pack={visuals?.companies?.[tab]}
            chartsLoading={chartsLoading}
          />
        )}

        <section className="mt-8 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]">
          <button
            onClick={() => setShowMethod((v) => !v)}
            aria-expanded={showMethod}
            className="w-full flex items-center justify-between gap-3 px-5 py-4 text-left cursor-pointer"
          >
            <span>
              <span className="block text-[14.5px] font-semibold text-[var(--color-ink)]">How this report was researched</span>
              <span className="block text-[12.5px] text-[var(--color-ink-faint)]">Which sources were consulted for each company, and why</span>
            </span>
            <span className={`text-[var(--color-ink-faint)] transition-transform ${showMethod ? "rotate-180" : ""}`}>▾</span>
          </button>
          {showMethod && (
            <div className="px-5 pb-5">
              <RoutingPanel routing={report.routing} routingTrace={report.routing_trace} embedded />
            </div>
          )}
        </section>

        {visuals?.as_of && (
          <p className="mt-4 text-[12px] text-[var(--color-ink-faint)]">
            Market data as of {formatDate(visuals.as_of)}. For informational purposes only; not investment advice.
          </p>
        )}
      </div>

      <FollowUpDrawer jobId={job.job_id} onOpenJob={onOpenJob} />
    </div>
  );
}
