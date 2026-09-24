export default function Logo({ size = "md", withWordmark = true }) {
  const markHeight = size === "sm" ? 26 : size === "lg" ? 44 : 32;
  const wordHeight = Math.round(markHeight * 0.62);
  return (
    <span className="inline-flex items-center gap-2.5">
      <img src="/brand/mark.png" alt="" aria-hidden="true" style={{ height: markHeight }} className="w-auto shrink-0" />
      {withWordmark && (
        <img src="/brand/wordmark.png" alt="ArthaNeeti" style={{ height: wordHeight }} className="w-auto shrink-0" />
      )}
    </span>
  );
}
