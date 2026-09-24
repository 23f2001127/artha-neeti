const EXAMPLES = [
  { label: "Full research view on TCS", query: "Give me a complete research view on TCS." },
  { label: "Compare TCS and Infosys", query: "Compare TCS and Infosys on fundamentals, sentiment and risk profile." },
  { label: "Review my portfolio", query: "I hold Reliance and HDFC Bank in equal amounts. How diversified is this portfolio?" },
  { label: "Is SBI fairly valued?", query: "Is State Bank of India fairly valued right now?" },
];

export default function ExampleChips({ onPick, disabled }) {
  return (
    <div className="flex flex-wrap gap-2">
      {EXAMPLES.map((ex) => (
        <button
          key={ex.label}
          type="button"
          disabled={disabled}
          onClick={() => onPick(ex.query)}
          className="text-[13px] px-3.5 py-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] hover:border-[var(--color-border-strong)] transition-colors disabled:opacity-50 cursor-pointer"
        >
          {ex.label}
        </button>
      ))}
    </div>
  );
}
