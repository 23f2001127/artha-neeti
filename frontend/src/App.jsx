import { motion } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import Header from "./components/layout/Header";
import LandingPage from "./components/landing/LandingPage";
import QueryView from "./components/query/QueryView";
import ProgressView from "./components/progress/ProgressView";
import ReportView from "./components/report/ReportView";
import { useJobPolling } from "./hooks/useJobPolling";
import { ThemeProvider } from "./lib/ThemeContext";
import { submitResearch } from "./lib/api";

function jobIdFromUrl() {
  return new URLSearchParams(window.location.search).get("job");
}

// Enter-only (no `exit`/AnimatePresence): confirmed live that this framer-
// motion/React 19 pairing never fires AnimatePresence's exit-complete
// callback, which either permanently freezes the view (mode="wait") or
// leaves the outgoing view's DOM stacked on top of the new one forever
// (default mode) - a real, reproducible bug, not a config choice. Plain
// key-based remount still unmounts the old view immediately and correctly;
// it just skips an exit animation, which is a fine trade for correctness.
const fade = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.25, ease: "easeOut" },
};

function AppShell() {
  const [jobId, setJobId] = useState(jobIdFromUrl);
  // Skip the landing pitch when arriving on a direct/shared job link.
  const [screen, setScreen] = useState(() => (jobIdFromUrl() ? "app" : "landing"));
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

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

  const goToQuery = useCallback(() => {
    setJobId(null);
    setScreen("app");
  }, []);
  // A follow-up that needed fresh research already has its job created
  // server-side (POST .../followups/escalate) - just switch to it, same as
  // handleSubmit does after POST /research.
  const onEscalate = useCallback((newJobId) => {
    setJobId(newJobId);
  }, []);
  const goToLanding = useCallback(() => {
    setJobId(null);
    setScreen("landing");
  }, []);
  // A gallery card on the landing page - same transition as opening a
  // shared ?job= link, just triggered from a click instead of the URL.
  const onViewJob = useCallback((viewJobId) => {
    setJobId(viewJobId);
    setScreen("app");
  }, []);

  if (screen === "landing") {
    return <LandingPage onLaunch={goToQuery} onViewJob={onViewJob} />;
  }

  let content;
  let key;
  if (!jobId) {
    key = "query";
    content = <QueryView onSubmit={handleSubmit} submitting={submitting} submitError={submitError} />;
  } else if (!job || job.status === "queued" || job.status === "running") {
    key = "progress";
    content = <ProgressView job={job} pollError={pollError} onNewQuery={goToQuery} />;
  } else {
    key = "report";
    content = <ReportView job={job} onNewQuery={goToQuery} onEscalate={onEscalate} />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-bg)]">
      <Header onLogoClick={goToLanding} />
      <main className="flex-1 w-full">
        <motion.div key={key} {...fade}>
          {content}
        </motion.div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AppShell />
    </ThemeProvider>
  );
}
