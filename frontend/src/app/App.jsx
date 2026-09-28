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

// Each screen has its own URL so the browser's back and forward buttons move
// between screens: "/" landing, "?view=research" the question form, "?job=<id>"
// a run in progress or its report.
function locationFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const jobId = params.get("job");
  if (jobId) return { screen: "app", jobId };
  if (params.get("view") === "research") return { screen: "app", jobId: null };
  return { screen: "landing", jobId: null };
}

function urlFor({ screen, jobId }) {
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  if (jobId) url.searchParams.set("job", jobId);
  else if (screen === "app") url.searchParams.set("view", "research");
  return url;
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
  const [location, setLocation] = useState(locationFromUrl);
  const { screen, jobId } = location;
  const pendingSection = useRef(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const { job, pollError } = useJobPolling(jobId);

  const go = useCallback((next, { scrollTop = true } = {}) => {
    const url = urlFor(next);
    if (url.href !== window.location.href) window.history.pushState({}, "", url);
    setLocation(next);
    if (scrollTop) window.scrollTo({ top: 0 });
  }, []);

  useEffect(() => {
    const onPop = () => {
      setLocation(locationFromUrl());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

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
      go({ screen: "app", jobId: job_id });
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  }, [go]);

  const goToQuery = useCallback(() => go({ screen: "app", jobId: null }), [go]);
  const goToLanding = useCallback(() => go({ screen: "landing", jobId: null }), [go]);
  const openJob = useCallback((viewJobId) => go({ screen: "app", jobId: viewJobId }), [go]);

  const navigateTo = useCallback(
    (sectionId) => {
      if (screen === "landing") {
        scrollToSection(sectionId);
      } else {
        pendingSection.current = sectionId;
        go({ screen: "landing", jobId: null }, { scrollTop: false });
      }
    },
    [screen, go],
  );

  let content;
  let key;
  if (screen === "landing") {
    key = "landing";
    content = <LandingPage onStart={goToQuery} onViewJob={openJob} />;
  } else if (!jobId) {
    key = "query";
    content = <QueryView onSubmit={handleSubmit} submitting={submitting} submitError={submitError} />;
  } else if (!job || job.status === "queued" || job.status === "running") {
    key = `progress-${jobId}`;
    content = <ProgressView job={job} pollError={pollError} onNewQuery={goToQuery} />;
  } else {
    key = `report-${jobId}`;
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
