import { useCallback, useEffect, useState } from "react";
import Header from "./components/layout/Header";
import QueryView from "./components/query/QueryView";
import ProgressView from "./components/progress/ProgressView";
import ReportView from "./components/report/ReportView";
import { useJobPolling } from "./hooks/useJobPolling";
import { submitResearch } from "./lib/api";

function jobIdFromUrl() {
  return new URLSearchParams(window.location.search).get("job");
}

export default function App() {
  const [jobId, setJobId] = useState(jobIdFromUrl);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  // Keep the job id in the URL so a run is shareable/refreshable.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (jobId) url.searchParams.set("job", jobId);
    else url.searchParams.delete("job");
    window.history.replaceState({}, "", url);
  }, [jobId]);

  const handleSubmit = useCallback(async (query) => {
    setSubmitError(null);
    setSubmitting(true);
    try {
      const { job_id } = await submitResearch(query);
      setJobId(job_id);
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  }, []);

  const handleReset = useCallback(() => setJobId(null), []);

  let content;
  if (!jobId) {
    content = <QueryView onSubmit={handleSubmit} submitting={submitting} submitError={submitError} />;
  } else if (!job || job.status === "queued" || job.status === "running") {
    content = <ProgressView job={job} pollError={pollError} onNewQuery={handleReset} />;
  } else {
    content = <ReportView job={job} onNewQuery={handleReset} />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-bg)]">
      <Header onLogoClick={handleReset} />
      <main className="flex-1 w-full">{content}</main>
    </div>
  );
}
