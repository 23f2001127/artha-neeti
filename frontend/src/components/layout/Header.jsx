import Logo from "./Logo";
import ThemeToggle from "./ThemeToggle";
import { GitHubIcon } from "../ui/icons";
import { REPO_URL } from "../../lib/links";

const NAV = [
  { id: "how-it-works", label: "How it works" },
  { id: "capabilities", label: "Capabilities" },
  { id: "examples", label: "Example reports" },
];

export default function Header({ onHome, onNavigate, onNewResearch }) {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-[var(--color-border)] bg-[var(--color-bg)]/85 backdrop-blur-md">
      <div className="page flex h-16 items-center justify-between gap-6">
        <button onClick={onHome} className="cursor-pointer" aria-label="ArthaNeeti home">
          <Logo />
        </button>

        <nav className="hidden md:flex items-center gap-1" aria-label="Primary">
          {NAV.map((item) => (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className="px-3 py-2 text-[13.5px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] rounded-[var(--radius-sm)] transition-colors cursor-pointer"
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label="View source on GitHub"
            className="hidden sm:inline-flex h-9 w-9 items-center justify-center rounded-full text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)] transition-colors"
          >
            <GitHubIcon className="h-[18px] w-[18px]" />
          </a>
          <ThemeToggle />
          <button
            onClick={onNewResearch}
            className="ml-1 h-9 px-4 text-[13.5px] font-semibold rounded-[var(--radius-sm)] bg-[var(--color-brand)] text-[var(--color-on-brand)]
                       hover:bg-[var(--color-brand-soft)] transition-colors cursor-pointer"
          >
            New research
          </button>
        </div>
      </div>
    </header>
  );
}
