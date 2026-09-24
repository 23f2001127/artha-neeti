import KpiStrip from "../../components/charts/KpiStrip";
import PriceChart from "../../components/charts/PriceChart";
import ReturnsChart from "../../components/charts/ReturnsChart";
import SentimentChart from "../../components/charts/SentimentChart";
import { MarginProfileChart, MarginTrendChart, RevenueProfitChart } from "../../components/charts/FinancialsChart";
import AnalysisSections from "./AnalysisSections";
import CaveatsPanel from "./CaveatsPanel";
import ConflictsPanel from "./ConflictsPanel";
import SourcesPanel from "./SourcesPanel";

function ChartSkeleton() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 h-[340px] rounded-[var(--radius-lg)] bg-[var(--color-surface)] border border-[var(--color-border)] animate-pulse" />
      <div className="h-[340px] rounded-[var(--radius-lg)] bg-[var(--color-surface)] border border-[var(--color-border)] animate-pulse" />
    </div>
  );
}

export default function CompanyDashboard({ ticker, report, pack, chartsLoading }) {
  if (!report || report.error) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-error)]/30 bg-[var(--color-error-tint)] p-6">
        <h3 className="text-[16px] font-semibold text-[var(--color-ink)]">{ticker}</h3>
        <p className="mt-1.5 text-[14px] text-[var(--color-ink-muted)]">
          We couldn't build a report for this company. None of the data sources returned usable results in this run.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {pack && <KpiStrip pack={pack} />}

      <section className="relative overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
        <div className="absolute inset-x-0 top-0 h-[3px] accent-rule-gradient" />
        <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.08em] text-[var(--color-brand)] mb-2.5">Summary</h3>
        <p className="text-[16px] leading-[1.7] text-[var(--color-ink)]">{report.executive_summary}</p>
      </section>

      {chartsLoading && !pack && <ChartSkeleton />}

      {pack && (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 min-w-0">
              <PriceChart history={pack.price_history} currency={pack.currency} name={pack.name} />
            </div>
            <ReturnsChart returns={pack.returns} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
            <RevenueProfitChart financials={pack.financials} />
            <MarginTrendChart financials={pack.financials} />
            <MarginProfileChart margins={pack.margins} />
          </div>
          {pack.sentiment && <SentimentChart sentiment={pack.sentiment} />}
        </>
      )}

      <AnalysisSections sections={report.sections} unavailable={report.unavailable} />
      <ConflictsPanel conflicts={report.conflicts_flagged} />
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-4 items-start">
        <SourcesPanel sourcesByClaim={report.sources_by_claim} />
        <CaveatsPanel caveats={report.overall_caveats} missingData={report.missing_data} />
      </div>
    </div>
  );
}
