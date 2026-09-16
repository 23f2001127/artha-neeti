import { motion } from "framer-motion";
import ThemeToggle from "../layout/ThemeToggle";
import HeroDiagram from "./HeroDiagram";
import StatCounter from "./StatCounter";

const STATS = [
  { value: 10, label: "companies with full filings coverage" },
  { value: 3980, label: "cited excerpts from real annual reports", suffix: "" },
  { value: 3, label: "specialist agents, selectively routed" },
  { value: 11, label: "tools across 3 MCP servers" },
];

const STEPS = [
  {
    n: "01",
    title: "Route",
    body: "A planner reads the question, resolves the compan(ies) to NSE tickers, and decides which specialists it actually needs — not a fixed pipeline. Every skip comes with a reason.",
  },
  {
    n: "02",
    title: "Gather",
    body: "Only the selected specialists run: live market data, recent news & sentiment, or retrieval over the company's own annual report — each grounded in a real tool call, not model memory.",
  },
  {
    n: "03",
    title: "Synthesize",
    body: "Findings are reconciled into one report. Where signals disagree — say, strong fundamentals against negative sentiment — it's flagged and explained, not smoothed into a bland average.",
  },
  {
    n: "04",
    title: "Compare",
    body: "For multi-company questions, a final pass produces a dimension-by-dimension comparison — without inventing an edge the data doesn't support.",
  },
];

const FEATURES = [
  {
    title: "Selective routing",
    body: "A narrow question about a share price dispatches one specialist. A full research view dispatches three. You see the decision and the reasoning behind every skip, live.",
  },
  {
    title: "Conflicts surfaced, not smoothed",
    body: "When market data and recent sentiment point different directions, the synthesis step names the tension and judges whether it's a real contradiction or just a different time horizon.",
  },
  {
    title: "Grounded in real filings",
    body: "Retrieval runs over the actual text of ten annual reports — page-anchored chunks, cited page numbers, and an honest flag when a figure comes from a flattened table.",
  },
  {
    title: "Nothing runs invisibly",
    body: "Routing decisions and per-specialist progress are visible while the system works, not just in the final report. Watch it reason, not a spinner.",
  },
];

function Section({ children, className = "" }) {
  return <section className={`mx-auto max-w-[1180px] px-6 ${className}`}>{children}</section>;
}

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1] } },
};
const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.09 } },
};

export default function LandingPage({ onLaunch }) {
  return (
    <div className="relative">
      {/* nav */}
      <div className="sticky top-0 z-30 border-b border-[var(--color-border)]/70 bg-[var(--color-bg)]/80 backdrop-blur-md">
        <Section className="flex items-center justify-between py-3.5">
          <div className="flex items-center gap-2.5">
            <svg width="26" height="26" viewBox="0 0 32 32" className="shrink-0">
              <rect width="32" height="32" rx="7" fill="var(--color-surface)" stroke="var(--color-border-strong)" />
              <path d="M9 22.5 L15.5 9 L22.5 22.5" stroke="var(--color-accent)" strokeWidth="2.1" fill="none" strokeLinejoin="round" strokeLinecap="round" />
              <path d="M11.6 17.3 H19.6" stroke="var(--color-accent)" strokeWidth="2.1" strokeLinecap="round" />
            </svg>
            <span className="text-[14.5px] font-semibold tracking-tight text-[var(--color-ink)]">ArthaNeeti</span>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="https://github.com/23f2001127/artha-neeti"
              target="_blank"
              rel="noreferrer"
              className="hidden sm:inline text-[12.5px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition-colors"
            >
              Source ↗
            </a>
            <ThemeToggle />
            <button
              onClick={onLaunch}
              className="text-[13px] font-medium px-3.5 py-1.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-bg)]
                         hover:brightness-110 transition-all cursor-pointer"
            >
              Launch
            </button>
          </div>
        </Section>
      </div>

      {/* hero */}
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 grid-veil pointer-events-none" />
        <Section className="relative pt-20 pb-24 grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-14 items-center">
          <motion.div initial="hidden" animate="show" variants={stagger}>
            <motion.span
              variants={fadeUp}
              className="inline-flex items-center gap-1.5 text-[11.5px] font-medium uppercase tracking-wider text-[var(--color-brand)] bg-[var(--color-brand-tint)] px-2.5 py-1 rounded-full mb-5"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-brand)]" />
              Multi-agent · Indian equities
            </motion.span>
            <motion.h1
              variants={fadeUp}
              className="text-[38px] sm:text-[46px] font-semibold tracking-tight leading-[1.08] text-[var(--color-ink)] mb-5"
            >
              Research that <span className="text-[var(--color-brand)]">shows its work.</span>
            </motion.h1>
            <motion.p variants={fadeUp} className="text-[16px] leading-relaxed text-[var(--color-ink-muted)] max-w-[520px] mb-8">
              Ask a question about any NSE-listed company. A planner routes it to the specialist agents
              it actually needs — market data, news &amp; sentiment, filings analysis — then reconciles
              what they find into one cited report. You watch every decision as it happens.
            </motion.p>
            <motion.div variants={fadeUp} className="flex items-center gap-3">
              <button
                onClick={onLaunch}
                className="text-[14px] font-medium px-5 py-2.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-bg)]
                           shadow-[var(--glow-brand)] hover:brightness-110 transition-all cursor-pointer"
              >
                Start researching →
              </button>
              <a
                href="https://github.com/23f2001127/artha-neeti"
                target="_blank"
                rel="noreferrer"
                className="text-[13.5px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] px-3 py-2.5 transition-colors"
              >
                Read the architecture ↗
              </a>
            </motion.div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
            className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]/80 backdrop-blur-sm p-6 shadow-[var(--shadow-card)]"
          >
            <p className="text-[11px] uppercase tracking-wide text-[var(--color-ink-faint)] mb-3">Live, while it runs</p>
            <HeroDiagram />
          </motion.div>
        </Section>
      </div>

      {/* stats */}
      <Section className="pb-20">
        <motion.div
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-60px" }}
          variants={stagger}
          className="grid grid-cols-2 lg:grid-cols-4 gap-px rounded-[var(--radius-lg)] overflow-hidden border border-[var(--color-border)]"
        >
          {STATS.map((s) => (
            <motion.div key={s.label} variants={fadeUp} className="bg-[var(--color-surface)] px-6 py-7">
              <div className="text-[30px] font-semibold text-[var(--color-brand)] tracking-tight">
                <StatCounter value={s.value} suffix={s.suffix} />
              </div>
              <p className="text-[12.5px] text-[var(--color-ink-muted)] leading-snug mt-1.5">{s.label}</p>
            </motion.div>
          ))}
        </motion.div>
      </Section>

      {/* how it works */}
      <Section className="pb-24">
        <motion.div initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} variants={stagger}>
          <motion.h2 variants={fadeUp} className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)] mb-8">
            How it works
          </motion.h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            {STEPS.map((s, i) => (
              <motion.div key={s.n} variants={fadeUp} className="relative">
                <span className="mono text-[13px] text-[var(--color-brand)]">{s.n}</span>
                <h3 className="text-[16px] font-semibold text-[var(--color-ink)] mt-2 mb-2">{s.title}</h3>
                <p className="text-[13.5px] leading-relaxed text-[var(--color-ink-muted)]">{s.body}</p>
                {i < STEPS.length - 1 && (
                  <div className="hidden md:block absolute top-1.5 -right-3 text-[var(--color-border-strong)]">→</div>
                )}
              </motion.div>
            ))}
          </div>
        </motion.div>
      </Section>

      {/* features */}
      <div className="border-y border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
        <Section className="py-24">
          <motion.div initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} variants={stagger}>
            <motion.h2 variants={fadeUp} className="text-[13px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)] mb-8">
              What makes this different from a chatbot wrapper
            </motion.h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              {FEATURES.map((f) => (
                <motion.div
                  key={f.title}
                  variants={fadeUp}
                  className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-6
                             hover:border-[var(--color-border-strong)] transition-colors"
                >
                  <h3 className="text-[15px] font-semibold text-[var(--color-ink)] mb-2">{f.title}</h3>
                  <p className="text-[13.5px] leading-relaxed text-[var(--color-ink-muted)]">{f.body}</p>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </Section>
      </div>

      {/* closing CTA */}
      <Section className="py-24 text-center">
        <motion.div
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-60px" }}
          variants={fadeUp}
          className="max-w-[560px] mx-auto"
        >
          <h2 className="text-[26px] font-semibold tracking-tight text-[var(--color-ink)] mb-3">
            Ask it something.
          </h2>
          <p className="text-[14.5px] text-[var(--color-ink-muted)] mb-7 leading-relaxed">
            Runs take a few minutes — the planner and specialists are doing real work, not returning a
            canned answer. You'll see exactly what they're doing the whole time.
          </p>
          <button
            onClick={onLaunch}
            className="text-[14px] font-medium px-6 py-2.5 rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-bg)]
                       shadow-[var(--glow-brand)] hover:brightness-110 transition-all cursor-pointer"
          >
            Start researching →
          </button>
        </motion.div>
      </Section>

      {/* footer */}
      <footer className="border-t border-[var(--color-border)]">
        <Section className="py-8 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-[12px] text-[var(--color-ink-faint)]">
            ArthaNeeti — built as a portfolio project. LangGraph · MCP · FastAPI · pgvector · Groq · Gemini.
          </p>
          <a
            href="https://github.com/23f2001127/artha-neeti"
            target="_blank"
            rel="noreferrer"
            className="text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition-colors"
          >
            View source ↗
          </a>
        </Section>
      </footer>
    </div>
  );
}
