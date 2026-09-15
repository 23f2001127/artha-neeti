// Best-effort, client-side only: which full-coverage company (if any) the free
// text of a query seems to name. This can never be as reliable as the Planner's
// own LLM-based ticker resolution (that happens server-side, after submit) - it
// exists purely to give an honest heads-up before the user waits minutes for a
// run, not to gate submission.
export function detectFullCoverageMatch(query, fullCoverageCompanies) {
  if (!query || !fullCoverageCompanies?.length) return null;
  const q = query.toLowerCase();
  for (const c of fullCoverageCompanies) {
    const needles = [c.ticker, c.name, ...(c.ticker === "M&M" ? ["mahindra"] : [])];
    if (needles.some((n) => n && q.includes(n.toLowerCase()))) return c;
  }
  return null;
}
