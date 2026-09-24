const SPECIALIST_LABEL = {
  market_data: "Market data",
  news_sentiment: "News & sentiment",
  filings: "Annual report",
};

export function specialistLabel(key) {
  return SPECIALIST_LABEL[key] || key;
}
