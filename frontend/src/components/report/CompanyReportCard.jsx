import CaveatsPanel from "./CaveatsPanel";
import ConflictsPanel from "./ConflictsPanel";
import SourcesPanel from "./SourcesPanel";
import SpecialistSections from "./SpecialistSections";

export default function CompanyReportCard({ ticker, report, heading = true }) {
  if (!report || report.error) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-error-tint)] bg-[var(--color-error-tint)] p-5">
        {heading && <h3 className="text-[15px] font-semibold text-[var(--color-ink)] mb-1">{ticker}</h3>}
        <p className="text-[13px] text-[var(--color-error)]">
          Could not build a report for this company: {report?.error || "unknown error"}
        </p>
      </div>
    );
  }

  return (
    <article className="space-y-5">
      {heading && (
        <div className="flex items-baseline gap-2 flex-wrap">
          <h3 className="text-[17px] font-semibold text-[var(--color-ink)]">
            {report.companies?.[0] || ticker}
          </h3>
          <span className="mono text-[12px] text-[var(--color-ink-faint)]">{ticker}</span>
        </div>
      )}

      <div className="relative overflow-hidden rounded-[var(--radius-lg)] bg-[var(--color-brand-tint)] px-5 py-4">
        <div className="absolute inset-x-0 top-0 h-[3px] accent-rule-gradient" />
        <p className="text-[15px] leading-relaxed text-[var(--color-ink)]">{report.executive_summary}</p>
      </div>

      <SpecialistSections sections={report.sections} />
      <ConflictsPanel conflicts={report.conflicts_flagged} />
      <SourcesPanel sourcesByClaim={report.sources_by_claim} />
      <CaveatsPanel caveats={report.overall_caveats} missingData={report.missing_data} />
    </article>
  );
}
