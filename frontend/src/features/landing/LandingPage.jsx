import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import HeroDiagram from "./HeroDiagram";
import StatCounter from "./StatCounter";
import ExampleGallery from "./ExampleGallery";
import { ArrowRightIcon } from "../../components/ui/icons";
import { getCompanies } from "../../lib/api";

const STEPS = [
  { title: "Ask", body: "Ask in plain English about one company, a head-to-head comparison, or a portfolio you hold." },
  { title: "Route", body: "A planner identifies the companies and decides which specialists the question actually needs." },
  { title: "Gather", body: "Specialists pull live prices and ratios, score recent news, and search the latest annual report." },
  { title: "Deliver", body: "Findings are reconciled into a cited report with charts, flagged conflicts and a downloadable PDF." },
];

const CAPABILITIES = [
  {
    title: "Live market data",
    body: "Price history, valuation multiples, profitability and balance-sheet ratios for any NSE listing.",
    icon: "M4 18l5-6 4 3 7-9M15 6h5v5",
  },
  {
    title: "Annual-report analysis",
    body: "Search across the company's own filing, with page-level citations behind every figure.",
    icon: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  },
  {
    title: "News sentiment",
    body: "Recent coverage scored article by article, so you can see what is driving market mood.",
    icon: "M4 5h16v11H8l-4 4zM8 9h8M8 12h5",
  },
  {
    title: "Conflict detection",
    body: "When fundamentals and sentiment disagree, the report says so and explains which signal to weigh.",
    icon: "M12 3l9 16H3zM12 10v4M12 17h.01",
  },
  {
    title: "Comparisons and portfolios",
    body: "Compare companies side by side, or review a portfolio's weighted valuation and concentration risk.",
    icon: "M5 20V10M12 20V4M19 20v-7",
  },
  {
    title: "Follow-up questions",
    body: "Ask follow-ups on any report. Answers stay grounded in the research that has already been done.",
    icon: "M21 12a8 8 0 0 1-11.8 7L4 20l1.1-4.2A8 8 0 1 1 21 12Z",
  },
];

const reveal = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] } },
};
const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.08 } } };
const inView = { initial: "hidden", whileInView: "show", viewport: { once: true, margin: "-60px" } };

function SectionHeading({ eyebrow, title, body }) {
  return (
    <motion.div variants={reveal} className="max-w-[640px] mb-10">
      <p className="text-[12px] font-semibold uppercase tracking-[0.1em] text-[var(--color-brand)]">{eyebrow}</p>
      <h2 className="font-display mt-3 text-[30px] sm:text-[36px] leading-tight font-semibold text-[var(--color-ink)]">{title}</h2>
      {body && <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-ink-muted)]">{body}</p>}
    </motion.div>
  );
}

export default function LandingPage({ onStart, onViewJob }) {
  const [companyCount, setCompanyCount] = useState(10);

  useEffect(() => {
    getCompanies()
      .then((data) => setCompanyCount(data?.full_coverage?.count || 10))
      .catch(() => {});
  }, []);

  const stats = [
    { value: companyCount, label: "Companies with annual-report coverage" },
    { value: 3980, label: "Indexed annual-report passages" },
    { value: 3, label: "Specialist research agents" },
    { value: 11, label: "Live data and retrieval tools" },
  ];

  return (
    <div>
      <section className="relative overflow-hidden border-b border-[var(--color-border)]">
        <div className="absolute inset-0 hero-glow pointer-events-none" />
        <div className="absolute inset-0 grid-veil pointer-events-none" />
        <div className="page relative grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] gap-12 xl:gap-16 items-center py-16 lg:py-24">
          <motion.div initial="hidden" animate="show" variants={stagger} className="min-w-0">
            <motion.p variants={reveal} className="inline-flex items-center gap-2 text-[12.5px] font-medium text-[var(--color-brand)] bg-[var(--color-brand-tint)] border border-[var(--color-brand)]/20 px-3 py-1 rounded-full">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-brand)]" />
              Equity research for Indian markets
            </motion.p>
            <motion.h1
              variants={reveal}
              className="font-display mt-6 text-[40px] sm:text-[52px] xl:text-[58px] leading-[1.05] font-semibold text-[var(--color-ink)]"
            >
              Research any NSE-listed company <span className="text-gold-gradient">in minutes.</span>
            </motion.h1>
            <motion.p variants={reveal} className="mt-6 max-w-[560px] text-[17px] leading-relaxed text-[var(--color-ink-muted)]">
              ArthaNeeti brings live market data, recent news and the company's own annual report together in one
              cited report, complete with charts, peer comparisons and a clear view of where the evidence disagrees.
            </motion.p>
            <motion.div variants={reveal} className="mt-9 flex flex-wrap items-center gap-3">
              <button
                onClick={onStart}
                className="inline-flex items-center gap-2 h-12 px-6 text-[15px] font-semibold rounded-[var(--radius-md)] bg-[var(--color-brand)] text-[var(--color-on-brand)] shadow-[var(--glow-brand)] hover:bg-[var(--color-brand-soft)] transition-colors cursor-pointer"
              >
                Start a research report
                <ArrowRightIcon className="h-4 w-4" />
              </button>
              <button
                onClick={() => document.getElementById("examples")?.scrollIntoView({ behavior: "smooth" })}
                className="h-12 px-6 text-[15px] font-semibold rounded-[var(--radius-md)] border border-[var(--color-border-strong)] text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)] transition-colors cursor-pointer"
              >
                See an example
              </button>
            </motion.div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
            className="min-w-0 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]/85 backdrop-blur-sm p-6 shadow-[var(--shadow-card)]"
          >
            <div className="flex items-center justify-between mb-4">
              <p className="text-[13px] font-semibold text-[var(--color-ink)]">Research pipeline</p>
              <span className="inline-flex items-center gap-1.5 text-[11.5px] text-[var(--color-ink-faint)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-ok)] pulse-dot" />
                Live
              </span>
            </div>
            <HeroDiagram />
          </motion.div>
        </div>
      </section>

      <section className="page py-14">
        <motion.div {...inView} variants={stagger} className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {stats.map((s) => (
            <motion.div
              key={s.label}
              variants={reveal}
              className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-6"
            >
              <p className="text-[34px] font-semibold text-[var(--color-ink)]">
                <StatCounter value={s.value} />
              </p>
              <p className="mt-1 text-[13px] text-[var(--color-ink-muted)]">{s.label}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      <section id="how-it-works" className="page py-16 scroll-mt-20">
        <motion.div {...inView} variants={stagger}>
          <SectionHeading
            eyebrow="How it works"
            title="From a question to a cited report"
            body="Every report is built from real tool calls against live data and filed documents, not from a model's memory."
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {STEPS.map((step, i) => (
              <motion.div
                key={step.title}
                variants={reveal}
                className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 min-w-0"
              >
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-brand-tint)] text-[13px] font-semibold text-[var(--color-brand)]">
                  {i + 1}
                </span>
                <h3 className="mt-4 text-[17px] font-semibold text-[var(--color-ink)]">{step.title}</h3>
                <p className="mt-2 text-[14px] leading-relaxed text-[var(--color-ink-muted)]">{step.body}</p>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </section>

      <section id="capabilities" className="border-y border-[var(--color-border)] bg-[var(--color-bg-elevated)] scroll-mt-16">
        <div className="page py-20">
          <motion.div {...inView} variants={stagger}>
            <SectionHeading
              eyebrow="Capabilities"
              title="Everything a research analyst would check"
              body="Three specialists cover the market, the news and the company's own disclosures, then a planner reconciles what they find."
            />
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {CAPABILITIES.map((c) => (
                <motion.div
                  key={c.title}
                  variants={reveal}
                  className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6 min-w-0 hover:border-[var(--color-border-strong)] transition-colors"
                >
                  <span className="inline-flex h-10 w-10 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-brand-tint)] text-[var(--color-brand)]">
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d={c.icon} />
                    </svg>
                  </span>
                  <h3 className="mt-4 text-[16px] font-semibold text-[var(--color-ink)]">{c.title}</h3>
                  <p className="mt-2 text-[14px] leading-relaxed text-[var(--color-ink-muted)]">{c.body}</p>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      <section id="examples" className="page py-20 scroll-mt-16">
        <motion.div {...inView} variants={stagger}>
          <SectionHeading
            eyebrow="Example reports"
            title="See what a finished report looks like"
            body="Real reports generated by ArthaNeeti, with live market data refreshed on open."
          />
          <motion.div variants={reveal}>
            <ExampleGallery onViewJob={onViewJob} />
          </motion.div>
        </motion.div>
      </section>

      <section className="page pb-24">
        <div className="relative overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] px-8 py-14 text-center">
          <div className="absolute inset-0 hero-glow pointer-events-none" />
          <div className="relative">
            <h2 className="font-display text-[30px] sm:text-[36px] font-semibold text-[var(--color-ink)]">Start with a question</h2>
            <p className="mx-auto mt-3 max-w-[520px] text-[15px] leading-relaxed text-[var(--color-ink-muted)]">
              Pick a company you follow and get a full research report, with charts and citations, in a few minutes.
            </p>
            <button
              onClick={onStart}
              className="mt-8 inline-flex items-center gap-2 h-12 px-7 text-[15px] font-semibold rounded-[var(--radius-md)] bg-[var(--color-brand)] text-[var(--color-on-brand)] shadow-[var(--glow-brand)] hover:bg-[var(--color-brand-soft)] transition-colors cursor-pointer"
            >
              Start a research report
              <ArrowRightIcon className="h-4 w-4" />
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
