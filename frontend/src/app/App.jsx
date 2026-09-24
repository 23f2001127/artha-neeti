import { motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import Header from "../components/layout/Header";
import Footer from "../components/layout/Footer";
import LandingPage from "../features/landing/LandingPage";
import QueryView from "../features/query/QueryView";
import ProgressView from "../features/progress/ProgressView";
import ReportView from "../features/report/ReportView";
import { useJobPolling } from "../hooks/useJobPolling";
import { ThemeProvider } from "./ThemeContext";
import { submitResearch } from "../lib/api";

function jobIdFromUrl() {
  return new URLSearchParams(window.location.search).get("job");
}

// Enter-only transitions: AnimatePresence exit tracking is unreliable with this
// framer-motion/React 19 pairing (leaves views stacked or frozen), and a keyed
// remount already unmounts the previous view.
const fade = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.28, ease: "easeOut" },
};

function scrollToSection(id) {
  requestAnimationFrame(() => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function AppShell() {
  const [jobId, setJobId] = useState(jobIdFromUrl);
  const [screen, setScreen] = useState(() => (jobIdFromUrl() ? "app" : "landing"));
  const pendingSection = useRef(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (jobId) url.searchParams.set("job", jobId);
    else url.searchParams.delete("job");
    window.history.replaceState({}, "", url);
  }, [jobId]);

  useEffect(() => {
    if (screen === "landing" && pendingSection.current) {
      scrollToSection(pendingSection.current);
      pendingSection.current = null;
    }
  }, [screen]);

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
    window.scrollTo({ top: 0 });
  }, []);

  const goToLanding = useCallback(() => {
    setJobId(null);
    setScreen("landing");
    window.scrollTo({ top: 0 });
  }, []);

  const navigateTo = useCallback(
    (sectionId) => {
      if (screen === "landing") {
        scrollToSection(sectionId);
      } else {
        setJobId(null);
        setScreen("landing");
        pendingSection.current = sectionId;
      }
    },
    [screen],
  );

  const openJob = useCallback((viewJobId) => {
    setJobId(viewJobId);
    setScreen("app");
    window.scrollTo({ top: 0 });
  }, []);

  let content;
  let key;
  if (screen === "landing") {
    key = "landing";
    content = <LandingPage onStart={goToQuery} onViewJob={openJob} />;
  } else if (!jobId) {
    key = "query";
    content = <QueryView onSubmit={handleSubmit} submitting={submitting} submitError={submitError} />;
  } else if (!job || job.status === "queued" || job.status === "running") {
    key = "progress";
    content = <ProgressView job={job} pollError={pollError} onNewQuery={goToQuery} />;
  } else {
    key = "report";
    content = <ReportView job={job} onNewQuery={goToQuery} onOpenJob={openJob} />;
  }

  return (
    <div className="min-h-screen flex flex-col bg-[var(--color-bg)]">
      <Header onHome={goToLanding} onNavigate={navigateTo} onNewResearch={goToQuery} />
      <main className="flex-1 w-full">
        <motion.div key={key} {...fade}>
          {content}
        </motion.div>
      </main>
      <Footer onNavigate={navigateTo} onNewResearch={goToQuery} />
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
