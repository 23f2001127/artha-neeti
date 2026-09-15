const EXAMPLES = [
  { label: "Reliance stock price", query: "What's Reliance's current stock price?" },
  { label: "Complete view on TCS", query: "Give me a complete research view on TCS." },
  { label: "TCS vs Infosys", query: "Compare TCS and Infosys on fundamentals, sentiment and risk profile." },
  { label: "SBI (partial coverage)", query: "Give me a full picture on State Bank of India." },
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
          className="text-[12.5px] px-3 py-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)]
                     text-[var(--color-ink-muted)] hover:text-[var(--color-brand)] hover:border-[var(--color-brand-soft)]
                     transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {ex.label}
        </button>
      ))}
    </div>
  );
}
