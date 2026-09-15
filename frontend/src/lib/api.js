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

/** GET /research/{job_id} -> full job state (status, routing_trace, specialist_status, report, error) */
export function getJob(jobId) {
  return request(`/research/${jobId}`);
}

/** GET /companies -> {full_coverage, partial_coverage} */
export function getCompanies() {
  return request("/companies");
}

export { ApiError };
