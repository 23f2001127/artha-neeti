import { motion } from "framer-motion";
import { useTheme } from "../../lib/ThemeContext";

export default function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${isDark ? "light" : "dark"} mode`}
      title={`Switch to ${isDark ? "light" : "dark"} mode`}
      className="relative h-8 w-8 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)]
                 hover:border-[var(--color-border-strong)] transition-colors cursor-pointer overflow-hidden shrink-0"
    >
      {/* Neither AnimatePresence's exit nor a from-zero entrance animate()
          reliably completes with this framer-motion/React 19 pairing
          (confirmed live) - a frequently-re-rendering parent (this sits
          under the polling app shell) can leave the tween permanently stuck
          mid-transition, invisible. initial={false} skips the animated
          entrance entirely and renders at the final state immediately -
          correctness over a pop-in flourish. Plain conditional rendering
          (no AnimatePresence) still unmounts the old icon correctly. */}
      {isDark ? (
        <motion.svg
          key="moon"
          viewBox="0 0 20 20"
          className="absolute inset-0 m-auto h-4 w-4"
          initial={false}
          animate={{ opacity: 1, rotate: 0, scale: 1 }}
        >
          <path
            d="M17 12.5A7 7 0 0 1 7.5 3 7.5 7.5 0 1 0 17 12.5Z"
            fill="var(--color-accent)"
          />
        </motion.svg>
      ) : (
        <motion.svg
          key="sun"
          viewBox="0 0 20 20"
          className="absolute inset-0 m-auto h-4 w-4"
          initial={false}
          animate={{ opacity: 1, rotate: 0, scale: 1 }}
        >
          <circle cx="10" cy="10" r="4" fill="var(--color-accent)" />
          {Array.from({ length: 8 }).map((_, i) => {
            const angle = (i * Math.PI) / 4;
            const x1 = 10 + Math.cos(angle) * 6.5;
            const y1 = 10 + Math.sin(angle) * 6.5;
            const x2 = 10 + Math.cos(angle) * 9;
            const y2 = 10 + Math.sin(angle) * 9;
            return (
              <line
                key={i}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke="var(--color-accent)"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            );
          })}
        </motion.svg>
      )}
    </button>
  );
}
