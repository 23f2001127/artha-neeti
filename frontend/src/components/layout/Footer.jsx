import Logo from "./Logo";
import { GitHubIcon } from "../ui/icons";
import { AUTHOR_GITHUB_URL, AUTHOR_NAME, REPO_URL } from "../../lib/links";

function FooterLink({ href, onClick, children }) {
  const className =
    "text-[13.5px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition-colors cursor-pointer text-left";
  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" className={className}>
        {children}
      </a>
    );
  }
  return (
    <button onClick={onClick} className={className}>
      {children}
    </button>
  );
}

function Column({ title, children }) {
  return (
    <div>
      <h3 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-[var(--color-ink-faint)] mb-4">{title}</h3>
      <div className="flex flex-col gap-2.5">{children}</div>
    </div>
  );
}

export default function Footer({ onNavigate, onNewResearch }) {
  const year = new Date().getFullYear();
  return (
    <footer className="w-full border-t border-[var(--color-border)] bg-[var(--color-bg-elevated)]">
      <div className="page py-14 grid grid-cols-2 md:grid-cols-[1.6fr_1fr_1fr_1fr] gap-10">
        <div className="col-span-2 md:col-span-1 max-w-[360px]">
          <Logo size="lg" />
          <p className="mt-5 text-[13.5px] leading-relaxed text-[var(--color-ink-muted)]">
            AI-powered research for NSE-listed companies. Live market data, news sentiment and annual-report
            analysis, combined into one cited report.
          </p>
        </div>

        <Column title="Product">
          <FooterLink onClick={onNewResearch}>New research</FooterLink>
          <FooterLink onClick={() => onNavigate("examples")}>Example reports</FooterLink>
          <FooterLink onClick={() => onNavigate("how-it-works")}>How it works</FooterLink>
        </Column>

        <Column title="Project">
          <FooterLink href={REPO_URL}>Source code</FooterLink>
          <FooterLink href={`${REPO_URL}#readme`}>Documentation</FooterLink>
          <FooterLink href={`${REPO_URL}/issues`}>Report an issue</FooterLink>
        </Column>

        <Column title="Author">
          <p className="text-[13.5px] text-[var(--color-ink)]">{AUTHOR_NAME}</p>
          <a
            href={AUTHOR_GITHUB_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 text-[13.5px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition-colors"
          >
            <GitHubIcon className="h-4 w-4" />
            GitHub
          </a>
        </Column>
      </div>

      <div className="border-t border-[var(--color-border)]">
        <div className="page py-5 flex flex-col md:flex-row md:items-center md:justify-between gap-2">
          <p className="text-[12.5px] text-[var(--color-ink-faint)]">
            © {year} {AUTHOR_NAME}. Designed and built by {AUTHOR_NAME}.
          </p>
          <p className="text-[12.5px] text-[var(--color-ink-faint)]">
            For informational purposes only. Not investment advice.
          </p>
        </div>
      </div>
    </footer>
  );
}
