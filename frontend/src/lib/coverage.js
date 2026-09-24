/** Best-effort match of a query against companies with annual-report coverage.
 * Advisory only; the planner resolves tickers authoritatively after submit. */
export function detectFullCoverageMatch(query, fullCoverageCompanies) {
  if (!query || !fullCoverageCompanies?.length) return null;
  const q = query.toLowerCase();
  for (const c of fullCoverageCompanies) {
    const needles = [c.ticker, c.name, ...(c.ticker === "M&M" ? ["mahindra"] : [])];
    if (needles.some((n) => n && q.includes(n.toLowerCase()))) return c;
  }
  return null;
}
