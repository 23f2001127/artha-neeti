import { readable } from "./prose";

const SPECIALIST_LABEL = {
  market_data: "Market data",
  news_sentiment: "News & sentiment",
  filings: "Annual report",
};

export function specialistLabel(key) {
  if (SPECIALIST_LABEL[key]) return SPECIALIST_LABEL[key];
  const text = readable(key || "");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
