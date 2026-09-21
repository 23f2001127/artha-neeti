// Thin client for the ArthaNeeti FastAPI backend. Relative /api/* in dev (Vite
// proxies it to the backend - see vite.config.js); VITE_API_BASE_DIRECT for a
// production build talking to a deployed backend directly.
const BASE = import.meta.env.VITE_API_BASE_DIRECT || "/api";

class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "content-type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch {
    throw new ApiError(
      "Could not reach the research API. Is the backend running (uvicorn app.main:app)?",
      0,
      null,
    );
  }
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(body?.detail || `Request failed (${res.status})`, res.status, body);
  }
  return body;
}

/** POST /research {query} -> {job_id, status} */
export function submitResearch(query) {
  return request("/research", { method: "POST", body: JSON.stringify({ query }) });
}

/** GET /research/{job_id} -> full job state: status, routing (structured
 * decision, live), routing_trace (raw log lines, for the trace toggle),
 * specialist_status, estimated_duration_seconds/_samples (a real historical
 * ETA, or null if there's no estimate yet), report, error */
export function getJob(jobId) {
  return request(`/research/${jobId}`);
}

/** GET /companies -> {full_coverage, partial_coverage} */
export function getCompanies() {
  return request("/companies");
}

/** GET /status -> {buckets: {<provider bucket>: {last_min_requests, last_min_tokens,
 * today_requests, today_tokens, limits, day_remaining, day_tokens_remaining}}} */
export function getStatus() {
  return request("/status");
}

/** POST /filings/upload (multipart) -> {job_id, status, ticker}. Not routed
 * through request() - a file upload needs a FormData body and no
 * content-type header (the browser sets the multipart boundary itself). */
export async function uploadFiling(file, { ticker, company, fiscalYear } = {}) {
  const form = new FormData();
  form.append("file", file);
  form.append("ticker", ticker);
  if (company) form.append("company", company);
  if (fiscalYear) form.append("fiscal_year", fiscalYear);

  let res;
  try {
    res = await fetch(`${BASE}/filings/upload`, { method: "POST", body: form });
  } catch {
    throw new ApiError(
      "Could not reach the research API. Is the backend running (uvicorn app.main:app)?",
      0,
      null,
    );
  }
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    throw new ApiError(body?.detail || `Request failed (${res.status})`, res.status, body);
  }
  return body;
}

/** POST /filings/fetch {ticker, company?, fiscal_year?} -> {job_id, status, ticker}
 * Best-effort: searches the web for the annual report and ingests it - no file needed. */
export function fetchFiling({ ticker, company, fiscalYear } = {}) {
  return request("/filings/fetch", {
    method: "POST",
    body: JSON.stringify({ ticker, company: company || null, fiscal_year: fiscalYear || null }),
  });
}

/** GET /filings/jobs/{job_id} -> status, chunks_done/chunks_total, source, source_url, detail, error.
 * Shared poll endpoint for both /filings/upload and /filings/fetch jobs. */
export function getFilingJob(jobId) {
  return request(`/filings/jobs/${jobId}`);
}

/** POST /research/{job_id}/followups {query} -> {sufficient_data, answer?, caveat?,
 * missing_reason?, standalone_query?, error?}. Fast (one LLM call, no job/poll). */
export function askFollowup(jobId, query) {
  return request(`/research/${jobId}/followups`, {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

/** GET /research/{job_id}/report.pdf -> triggers a real .pdf file download.
 * Fetched as a Blob rather than a plain <a href> because of the same dev-proxy /
 * VITE_API_BASE_DIRECT split every other call already goes through `request()` for. */
export async function downloadReportPdf(jobId, filename = "arthaneeti-report.pdf") {
  let res;
  try {
    res = await fetch(`${BASE}/research/${jobId}/report.pdf`);
  } catch {
    throw new ApiError(
      "Could not reach the research API. Is the backend running (uvicorn app.main:app)?",
      0,
      null,
    );
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      detail = (await res.json())?.detail || detail;
    } catch {
      // body wasn't JSON - keep the generic message
    }
    throw new ApiError(detail, res.status, null);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** GET /research/{job_id}/followups -> {conversation_id, turns: [...]} */
export function getFollowups(jobId) {
  return request(`/research/${jobId}/followups`);
}

/** POST /research/{job_id}/followups/escalate {standalone_query} -> {job_id, status}
 * Starts a real Planner run continuing this conversation - poll it like any other job. */
export function escalateFollowup(jobId, standaloneQuery) {
  return request(`/research/${jobId}/followups/escalate`, {
    method: "POST",
    body: JSON.stringify({ standalone_query: standaloneQuery }),
  });
}

export { ApiError };
