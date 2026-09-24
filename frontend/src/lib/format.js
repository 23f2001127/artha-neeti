const CRORE = 1e7;
const LAKH_CRORE = 1e12;

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

export function currencySymbol(currency) {
  return !currency || currency === "INR" ? "₹" : `${currency} `;
}

/** Large rupee amounts in the units Indian markets report them in. */
export function formatMoney(value, currency = "INR") {
  if (!isNum(value)) return "—";
  const sym = currencySymbol(currency);
  const abs = Math.abs(value);
  if (currency === "INR" || !currency) {
    if (abs >= LAKH_CRORE) return `${sym}${(value / LAKH_CRORE).toFixed(2)}L Cr`;
    if (abs >= CRORE) return `${sym}${Math.round(value / CRORE).toLocaleString("en-IN")} Cr`;
  }
  return `${sym}${compact(value)}`;
}

/** Crore value for chart axes. */
export function toCrore(value) {
  return isNum(value) ? value / CRORE : null;
}

export function formatCroreAxis(value) {
  if (!isNum(value)) return "";
  if (Math.abs(value) >= 1e5) return `${(value / 1e5).toFixed(1)}L`;
  return Math.round(value).toLocaleString("en-IN");
}

export function formatPrice(value, currency = "INR") {
  if (!isNum(value)) return "—";
  return `${currencySymbol(currency)}${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPct(value, { signed = false, digits = 1 } = {}) {
  if (!isNum(value)) return "—";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatMultiple(value, digits = 1) {
  return isNum(value) ? `${value.toFixed(digits)}x` : "—";
}

export function formatByUnit(value, unit) {
  if (unit === "%") return formatPct(value);
  if (unit === "x") return formatMultiple(value);
  return isNum(value) ? value.toLocaleString("en-IN") : "—";
}

export function compact(value) {
  if (!isNum(value)) return "—";
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function formatDate(value, opts = { day: "numeric", month: "short", year: "numeric" }) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-IN", opts);
}

export function formatShortDate(value) {
  return formatDate(value, { day: "numeric", month: "short" });
}

export function formatMonth(value) {
  return formatDate(value, { month: "short", year: "2-digit" });
}
