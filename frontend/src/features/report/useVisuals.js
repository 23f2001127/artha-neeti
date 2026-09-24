import { useEffect, useState } from "react";
import { getVisuals } from "../../lib/api";

/** Chart data for a finished report: embedded in the report when present,
 * otherwise fetched (and generated server-side) on demand. */
export function useVisuals(job) {
  const embedded = job?.report?.visuals || null;
  const jobId = job?.job_id;
  const shouldFetch = !embedded && Boolean(jobId) && job?.status === "done";
  const [result, setResult] = useState({ jobId: null, visuals: null, settled: false });

  useEffect(() => {
    if (!shouldFetch) return undefined;
    let cancelled = false;
    getVisuals(jobId)
      .then((visuals) => !cancelled && setResult({ jobId, visuals, settled: true }))
      .catch(() => !cancelled && setResult({ jobId, visuals: null, settled: true }));
    return () => {
      cancelled = true;
    };
  }, [shouldFetch, jobId]);

  const current = result.jobId === jobId ? result : { visuals: null, settled: false };
  return {
    visuals: embedded || current.visuals,
    loading: shouldFetch && !current.settled,
  };
}
