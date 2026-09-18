import { useEffect, useRef, useState } from "react";
import { getJob } from "../lib/api";

const POLL_MS = 2500;
const TERMINAL = new Set(["done", "error"]);

/** Polls GET /research/{jobId} until the job reaches a terminal state.
 * Returns the latest job payload as-is (status, routing, routing_trace,
 * specialist_status, estimated_duration_seconds/_samples, report, error) plus
 * a transport-level error, if the API itself was unreachable. */
export function useJobPolling(jobId) {
  const [job, setJob] = useState(null);
  const [pollError, setPollError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    setJob(null);
    setPollError(null);

    async function tick() {
      try {
        const data = await getJob(jobId);
        if (cancelled) return;
        setJob(data);
        setPollError(null);
        if (!TERMINAL.has(data.status)) {
          timer.current = setTimeout(tick, POLL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        setPollError(err.message || "Lost contact with the research API.");
        timer.current = setTimeout(tick, POLL_MS * 2);
      }
    }
    tick();

    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [jobId]);

  return { job, pollError };
}
