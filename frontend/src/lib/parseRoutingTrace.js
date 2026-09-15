// The live poll endpoint only exposes the Planner's raw routing_trace log lines
// (the structured `routing` object - specialists_selected/skipped with reasons,
// rationale - only lands inside report.routing once the job is `done`; see
// app/jobs.py's progress writer). This reconstructs the same structure from the
// trace lines so the routing panel can show it live. The line formats come from
// agents/planner.py's _route_node and are stable/documented; anything that
// doesn't match is kept as a plain trace line instead of dropped.
const COMPANY_RE =
  /^company '(.+)' -> ([\w&]+)\.NS: (RESOLVABLE|NOT resolvable) \((.+)\); (in|NOT in) filings corpus$/;
const ACTION_RE = /^\s*->\s*([\w&]+):\s*(call|skip)\s+(market_data|news_sentiment|filings)\s*-\s*(.+)$/;
const DROPPED_RE = /^\s*->\s*(.+?):\s*no usable data source/;
const NONE_APPLICABLE_RE = /^\s*->\s*([\w&]+):\s*no applicable specialists/;
const RATIONALE_RE = /^LLM rationale:\s*(.+)$/;

export function parseRoutingTrace(lines) {
  if (!Array.isArray(lines) || lines.length === 0) return null;

  const companies = []; // [{name, ticker, resolvable, note, inCorpus}]
  const byTicker = new Map(); // ticker -> {selected: [{specialist,reason}], skipped: [{specialist,reason}]}
  let rationale = null;
  const unmatched = [];

  const ensure = (ticker) => {
    if (!byTicker.has(ticker)) byTicker.set(ticker, { selected: [], skipped: [] });
    return byTicker.get(ticker);
  };

  for (const line of lines) {
    let m;
    if ((m = line.match(RATIONALE_RE))) {
      rationale = m[1];
      continue;
    }
    if ((m = line.match(COMPANY_RE))) {
      const [, name, ticker, resolvability, note, corpus] = m;
      companies.push({
        name,
        ticker,
        resolvable: resolvability === "RESOLVABLE",
        note,
        inCorpus: corpus === "in",
      });
      ensure(ticker);
      continue;
    }
    if ((m = line.match(ACTION_RE))) {
      const [, ticker, verb, specialist, reason] = m;
      const bucket = ensure(ticker);
      (verb === "call" ? bucket.selected : bucket.skipped).push({ specialist, reason });
      continue;
    }
    if ((m = line.match(DROPPED_RE)) || (m = line.match(NONE_APPLICABLE_RE))) {
      continue; // covered by the company card's own resolvable/inCorpus flags
    }
    if (line.startsWith("routing query:")) continue; // shown as the query itself elsewhere
    unmatched.push(line);
  }

  if (companies.length === 0 && byTicker.size === 0) return null;

  return {
    rationale,
    companies: companies.map((c) => ({ ...c, ...byTicker.get(c.ticker) })),
    unmatched,
  };
}
