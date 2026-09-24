import { useEffect, useRef, useState } from "react";
import { CheckIcon, LinkIcon, LinkedInIcon, MailIcon, ShareIcon, XIcon } from "../../components/ui/icons";

function MenuItem({ icon: Icon, children, ...props }) {
  const Tag = props.href ? "a" : "button";
  return (
    <Tag
      {...props}
      className="w-full flex items-center gap-3 px-3 py-2 text-[13.5px] text-[var(--color-ink)] rounded-[var(--radius-sm)] hover:bg-[var(--color-surface-muted)] transition-colors cursor-pointer"
    >
      <Icon className="h-4 w-4 text-[var(--color-ink-muted)]" />
      {children}
    </Tag>
  );
}

export default function ShareMenu({ jobId, title }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef(null);

  const url = `${window.location.origin}/?job=${jobId}`;
  const text = `${title} — research report on ArthaNeeti`;
  const canNativeShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      window.prompt("Copy this link", url);
    }
  }

  async function nativeShare() {
    try {
      await navigator.share({ title: "ArthaNeeti research report", text, url });
      setOpen(false);
    } catch {
      // dismissed by the user
    }
  }

  const encoded = encodeURIComponent(url);
  const encodedText = encodeURIComponent(text);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-2 h-10 px-4 text-[13.5px] font-medium rounded-[var(--radius-sm)] border border-[var(--color-border-strong)] text-[var(--color-ink)] hover:bg-[var(--color-surface-muted)] transition-colors cursor-pointer"
      >
        <ShareIcon className="h-4 w-4" />
        Share
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-12 z-30 w-60 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-1.5 shadow-[var(--shadow-card)] fade-up"
        >
          <MenuItem icon={copied ? CheckIcon : LinkIcon} onClick={copyLink}>
            {copied ? "Link copied" : "Copy link"}
          </MenuItem>
          {canNativeShare && (
            <MenuItem icon={ShareIcon} onClick={nativeShare}>
              Share via…
            </MenuItem>
          )}
          <div className="my-1 h-px bg-[var(--color-border)]" />
          <MenuItem icon={LinkedInIcon} href={`https://www.linkedin.com/sharing/share-offsite/?url=${encoded}`} target="_blank" rel="noreferrer">
            LinkedIn
          </MenuItem>
          <MenuItem icon={XIcon} href={`https://twitter.com/intent/tweet?url=${encoded}&text=${encodedText}`} target="_blank" rel="noreferrer">
            X
          </MenuItem>
          <MenuItem icon={MailIcon} href={`mailto:?subject=${encodeURIComponent("ArthaNeeti research report")}&body=${encodedText}%0A%0A${encoded}`}>
            Email
          </MenuItem>
        </div>
      )}
    </div>
  );
}
