export default function Header({ onLogoClick }) {
  return (
    <header className="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="mx-auto max-w-[1180px] px-6 py-4 flex items-center justify-between">
        <button
          onClick={onLogoClick}
          className="flex items-center gap-3 group cursor-pointer"
          title="Start a new query"
        >
          <svg width="30" height="30" viewBox="0 0 32 32" className="shrink-0">
            <rect width="32" height="32" rx="7" fill="var(--color-brand)" />
            <path
              d="M9 22.5 L15.5 9 L22.5 22.5"
              stroke="var(--color-accent)"
              strokeWidth="2.1"
              fill="none"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <path d="M11.6 17.3 H19.6" stroke="var(--color-accent)" strokeWidth="2.1" strokeLinecap="round" />
          </svg>
          <div className="text-left">
            <div className="text-[15px] font-semibold tracking-tight text-[var(--color-ink)] leading-none group-hover:text-[var(--color-brand)] transition-colors">
              ArthaNeeti
            </div>
            <div className="text-[11px] text-[var(--color-ink-faint)] leading-none mt-1">
              Indian equity research, multi-agent
            </div>
          </div>
        </button>
        <a
          href="https://github.com/23f2001127/artha-neeti"
          target="_blank"
          rel="noreferrer"
          className="text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-brand)] transition-colors"
        >
          Source ↗
        </a>
      </div>
    </header>
  );
}
