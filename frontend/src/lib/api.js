// Requests go to /api, proxied by Vite in development and by nginx in the
// container image. VITE_API_BASE_DIRECT points a build at an API on another origin.
const BASE = import.meta.env.VITE_API_BASE_DIRECT || "/api";

const UNREACHABLE = "We couldn't reach the ArthaNeeti service. Check your connection and try again.";

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function send(path, options = {}) {
  try {
    return await fetch(`${BASE}${path}`, options);
  } catch {
    throw new ApiError(UNREACHABLE, 0, null);
  }
}

async function errorFrom(res) {
  let detail = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // non-JSON error body
  }
  return new ApiError(detail, res.status, null);
}

async function request(path, options = {}) {
  const res = await send(path, {
    ...options,
    headers: { "content-type": "application/json", ...(options.headers || {}) },
  });
  if (!res.ok) throw await errorFrom(res);
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export function submitResearch(query) {
  return request("/research", { method: "POST", body: JSON.stringify({ query }) });
}

export function getJob(jobId) {
  return request(`/research/${jobId}`);
}

export function getVisuals(jobId) {
  return request(`/research/${jobId}/visuals`);
}

export function getCompanies() {
  return request("/companies");
}

export function getStatus() {
  return request("/status");
}

export async function uploadFiling(file, { ticker, company, fiscalYear } = {}) {
  const form = new FormData();
  form.append("file", file);
  form.append("ticker", ticker);
  if (company) form.append("company", company);
  if (fiscalYear) form.append("fiscal_year", fiscalYear);
  // No content-type header: the browser sets the multipart boundary.
  const res = await send("/filings/upload", { method: "POST", body: form });
  if (!res.ok) throw await errorFrom(res);
  return res.json();
}

export function fetchFiling({ ticker, company, fiscalYear } = {}) {
  return request("/filings/fetch", {
    method: "POST",
    body: JSON.stringify({ ticker, company: company || null, fiscal_year: fiscalYear || null }),
  });
}

export function getFilingJob(jobId) {
  return request(`/filings/jobs/${jobId}`);
}

export function askFollowup(jobId, query) {
  return request(`/research/${jobId}/followups`, { method: "POST", body: JSON.stringify({ query }) });
}

export function getFollowups(jobId) {
  return request(`/research/${jobId}/followups`);
}

export function escalateFollowup(jobId, standaloneQuery) {
  return request(`/research/${jobId}/followups/escalate`, {
    method: "POST",
    body: JSON.stringify({ standalone_query: standaloneQuery }),
  });
}

export async function downloadReportPdf(jobId, filename = "arthaneeti-report.pdf") {
  const res = await send(`/research/${jobId}/report.pdf`);
  if (!res.ok) throw await errorFrom(res);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
