"""Renders a finished Planner report into a downloadable PDF.

Two-step, matching the shape every other "turn structured data into a
document" piece of this codebase uses: build a plain string first
(``render_report_html``), then a thin conversion call
(``render_report_pdf``). HTML/CSS here is deliberately conservative -
``xhtml2pdf`` (pure Python, no system dependency - see app/README.md for why
this was chosen over weasyprint) supports a real but limited CSS subset: no
flexbox, no border-radius, no border-collapse. Layout is plain block markup
and `<table>`, not the app's own Tailwind classes.
"""

from __future__ import annotations

import base64
import html
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xhtml2pdf import pisa

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The frontend's SpecialistSections.jsx prefixes these with a glyph
# (ICON = {"market_data": "▲", ...}) rendered by a real browser font.
# Helvetica (this PDF's base font - see the Unicode note below) does NOT cover
# that glyph block - checked, not assumed - so it would render as a blank box,
# the exact bug already fixed once for the rupee sign. Plain labels only here;
# the visual echo of the web app comes from the new border-left accent
# instead. Always pass through _esc() - a literal "&" is fine, an HTML entity
# baked into this dict is not (it would get double-escaped).
_SPECIALIST_LABEL = {
    "market_data": "Market Data",
    "news_sentiment": "News & Sentiment",
    "filings": "Filings",
}


def _logo_data_uri() -> str:
    path = _REPO_ROOT / "assets" / "brand" / "mark.png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


# Computed once at import time - a data URI, not a filesystem path, so the
# PDF is self-contained and immune to xhtml2pdf's relative-path resolution
# depending on the process's cwd.
_LOGO_DATA_URI = _logo_data_uri()

_CSS = """
@page {
    size: A4;
    margin: 2.2cm 1.8cm 2.6cm 1.8cm;
    @frame footer_frame {
        -pdf-frame-content: footer_content;
        bottom: 1.1cm;
        margin-left: 1.8cm;
        margin-right: 1.8cm;
        height: 1cm;
    }
}
body { font-family: Helvetica, Arial, sans-serif; color: #181a17; font-size: 10.5pt; line-height: 1.45; }
h1 { color: #12332c; font-size: 19pt; margin: 0; }
h2 { color: #12332c; font-size: 14pt; margin: 22px 0 8px 0; border-bottom: 1px solid #cbc7b9; padding-bottom: 4px; }
h3 { color: #1f4f44; font-size: 11.5pt; margin: 14px 0 4px 0; }
h3.spec-heading { border-left: 3px solid #b9822f; padding-left: 8px; }
p { margin: 4px 0; }
.header-table { width: 100%; margin: 0 0 2px 0; }
.header-table td { border: none; padding: 0; vertical-align: middle; }
.header-table .logo-cell { width: 44px; }
.header-table img { width: 36px; height: 36px; }
.accent-rule { height: 2px; background-color: #b9822f; margin: 8px 0 14px 0; }
.meta { color: #5a5d55; font-size: 9pt; margin: 0 0 4px 0; }
.mode-badge { display: inline-block; background: #12332c; color: #ffffff; padding: 2px 9px; font-size: 8.5pt; margin: 0 0 16px 0; }
.summary-block { background: #e9efec; padding: 10px 12px; margin: 8px 0 4px 0; }
.summary-block p { margin: 0; }
.tag { background: #e9efec; color: #12332c; padding: 1px 6px; font-size: 8.5pt; border: 1px solid #cbc7b9; }
table { width: 100%; font-size: 9.5pt; margin: 8px 0; }
th, td { border: 1px solid #cbc7b9; padding: 5px 7px; text-align: left; vertical-align: top; }
th { background: #f1f0eb; }
.claim { margin: 6px 0; padding-left: 10px; border-left: 2px solid #cbc7b9; }
.claim .caveat { color: #8d9086; font-style: italic; font-size: 9pt; }
.conflict { background: #fcf1de; border: 1px solid #e7bd7c; padding: 8px 10px; margin: 8px 0; }
.conflict .topic { color: #a8630a; font-weight: bold; }
.caveats { color: #5a5d55; font-size: 9pt; }
.caveats li { margin: 2px 0; }
.footer { color: #8d9086; font-size: 8pt; margin-top: 28px; border-top: 1px solid #e1ded4; padding-top: 8px; }
#footer_content { color: #8d9086; font-size: 8pt; }
"""


# The PDF's base font (Helvetica, one of the standard 14 PDF fonts - no
# embedding, so no font file to bundle/license) only covers WinAnsi/Latin-1.
# Groq output regularly carries characters outside that range - Unicode
# hyphens (a known quirk, see agents/README.md's Filings Agent notes),
# curly quotes, and the rupee sign are all real content in these reports,
# not edge cases - so normalize to ASCII-safe equivalents rather than let
# them render as blank boxes.
_UNICODE_ASCII_MAP = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "--", "―": "--",
    "‘": "'", "’": "'", "‚": "'",
    "“": '"', "”": '"', "„": '"',
    " ": " ",
    "₹": "Rs. ",
    "≈": "~", "≥": ">=", "≤": "<=", "×": "x",
    "•": "-", "…": "...", "→": "->",
}


def _sanitize(text: str) -> str:
    for src, dst in _UNICODE_ASCII_MAP.items():
        text = text.replace(src, dst)
    return text


def _esc(text: Any) -> str:
    return html.escape(_sanitize(str(text))) if text is not None else ""


def _claims_html(sources_by_claim: dict) -> str:
    if not sources_by_claim:
        return ""
    rows = []
    for claim, meta in sources_by_claim.items():
        sources = ", ".join(_SPECIALIST_LABEL.get(s.split(" ")[0], s) for s in (meta.get("sources") or []))
        caveat = f'<div class="caveat">-- {_esc(meta.get("caveat"))}</div>' if meta.get("caveat") else ""
        rows.append(
            f'<div class="claim"><p>{_esc(claim)}</p>'
            f'<span class="tag">{_esc(sources) or "unattributed"}</span>{caveat}</div>'
        )
    return "<h3>Key claims &amp; sources</h3>" + "".join(rows)


def _conflicts_html(conflicts: list) -> str:
    if not conflicts:
        return ""
    blocks = []
    for c in conflicts:
        blocks.append(
            f'<div class="conflict"><div class="topic">{_esc(c.get("topic"))}</div>'
            f'<p><b>{_esc(_SPECIALIST_LABEL.get(c.get("specialist_a"), c.get("specialist_a")))}:</b> '
            f'{_esc(c.get("position_a"))}</p>'
            f'<p><b>{_esc(_SPECIALIST_LABEL.get(c.get("specialist_b"), c.get("specialist_b")))}:</b> '
            f'{_esc(c.get("position_b"))}</p>'
            f'<p><i>Reconciled -- {_esc(c.get("assessment"))}</i></p></div>'
        )
    return "<h3>Conflicting signals</h3>" + "".join(blocks)


def _caveats_html(title: str, caveats: list) -> str:
    if not caveats:
        return ""
    items = "".join(f"<li>{_esc(c)}</li>" for c in caveats)
    return f'<h3>{_esc(title)}</h3><ul class="caveats">{items}</ul>'


def _company_report_html(ticker: str, report: dict) -> str:
    if not isinstance(report, dict) or "error" in report:
        reason = _esc((report or {}).get("error", "no report available"))
        return f"<h2>{_esc(ticker)}</h2><p><i>This company's report failed: {reason}</i></p>"

    company = (report.get("companies") or [ticker])[0]
    sections = report.get("sections") or {}
    section_html = "".join(
        f'<h3 class="spec-heading">{_esc(_SPECIALIST_LABEL.get(key, key))}</h3><p>{_esc(text)}</p>'
        for key, text in sections.items()
        if text
    )
    return (
        f"<h2>{_esc(company)} ({_esc(ticker)})</h2>"
        f'<div class="summary-block"><p>{_esc(report.get("executive_summary"))}</p></div>'
        f"{section_html}"
        f"{_claims_html(report.get('sources_by_claim') or {})}"
        f"{_conflicts_html(report.get('conflicts_flagged') or [])}"
        f"{_caveats_html('Caveats', report.get('overall_caveats') or [])}"
        f"{_caveats_html('Missing data', report.get('missing_data') or [])}"
    )


def _comparison_html(comparison: dict) -> str:
    rows = "".join(
        f"<tr><td>{_esc(d.get('dimension'))}</td><td>{_esc(d.get('assessment'))}</td>"
        f"<td>{_esc(d.get('edge') or 'comparable')}</td></tr>"
        for d in (comparison.get("dimensions") or [])
    )
    table = (
        f"<table><tr><th>Dimension</th><th>Assessment</th><th>Edge</th></tr>{rows}</table>"
        if rows else ""
    )
    return (
        "<h2>Comparison</h2>"
        f"<p>{_esc(comparison.get('verdict'))}</p>"
        f"{table}"
        f"{_caveats_html('Caveats', comparison.get('caveats') or [])}"
    )


def _portfolio_html(portfolio: dict) -> str:
    holdings = portfolio.get("holdings") or []
    rows = "".join(
        f"<tr><td>{_esc(h.get('ticker'))}</td><td>{_esc(h.get('weight_pct'))}%</td>"
        f"<td>{_esc(h.get('sector') or '—')}</td>"
        f"<td>{_esc(h.get('pe_ratio') if h.get('pe_ratio') is not None else '—')}</td>"
        f"<td>{_esc(h.get('roe') if h.get('roe') is not None else '—')}%</td>"
        f"<td>{_esc(h.get('dividend_yield_pct') if h.get('dividend_yield_pct') is not None else '—')}%</td></tr>"
        for h in holdings
    )
    holdings_table = (
        "<table><tr><th>Ticker</th><th>Weight</th><th>Sector</th><th>P/E</th>"
        f"<th>ROE</th><th>Div. yield</th></tr>{rows}</table>"
    )
    sector_rows = "".join(
        f"<tr><td>{_esc(sector)}</td><td>{_esc(pct)}%</td></tr>"
        for sector, pct in (portfolio.get("sector_allocation_pct") or {}).items()
    )
    sector_table = f"<table><tr><th>Sector</th><th>Allocation</th></tr>{sector_rows}</table>" if sector_rows else ""

    def _metric(label: str, value: Any, suffix: str = "") -> str:
        shown = f"{value}{suffix}" if value is not None else "—"
        return f"<td><b>{_esc(label)}:</b> {_esc(shown)}</td>"

    metrics_row = (
        "<table><tr>"
        + _metric("Weighted P/E", portfolio.get("weighted_pe_ratio"))
        + _metric("Weighted ROE", portfolio.get("weighted_roe"), "%")
        + _metric("Weighted dividend yield", portfolio.get("weighted_dividend_yield_pct"), "%")
        + "</tr></table>"
    )
    risks = "".join(f"<li>{_esc(r)}</li>" for r in (portfolio.get("concentration_risks") or []))
    risks_html = (
        f'<h3>Concentration risks</h3><ul class="caveats">{risks}</ul>' if risks else ""
    )
    return (
        "<h2>Portfolio analysis</h2>"
        f"<p>{_esc(portfolio.get('narrative'))}</p>"
        f"{holdings_table}"
        f"{metrics_row}"
        f"<h3>Sector allocation</h3>{sector_table}"
        f"<h3>Diversification</h3><p>{_esc(portfolio.get('diversification'))}</p>"
        f"{risks_html}"
        f"{_caveats_html('Caveats', portfolio.get('caveats') or [])}"
    )


def _mode_badge(report: dict) -> str:
    if report.get("portfolio"):
        return "Portfolio analysis"
    if report.get("comparison"):
        return "Comparison"
    if report.get("mode") == "multi":
        return "Multi-company"
    return "Single company"


def render_report_html(report: dict) -> str:
    """A self-contained HTML document (inline <style>, no external assets -
    xhtml2pdf doesn't reliably fetch remote fonts/CSS) for one finished
    Planner report. Mirrors the frontend's ReportView content, in a
    print-appropriate document layout rather than the app's card/chat UI."""
    mode = report.get("mode", "none")
    query = report.get("query", "")
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    if mode == "none":
        body = f"<p><i>{_esc(report.get('note') or 'No company could be resolved for this query.')}</i></p>"
    else:
        reports = report.get("reports") or {}
        body = "".join(_company_report_html(t, r) for t, r in reports.items())
        if report.get("comparison"):
            body += _comparison_html(report["comparison"])
        if report.get("portfolio"):
            body += _portfolio_html(report["portfolio"])

    header = f"""
<table class="header-table"><tr>
<td class="logo-cell"><img src="{_LOGO_DATA_URI}"/></td>
<td><h1>ArthaNeeti Research Report</h1><p class="meta">{_esc(query)}</p></td>
</tr></table>
<div class="accent-rule"></div>
<div class="mode-badge">{_esc(_mode_badge(report))}</div>
"""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><style>{_CSS}</style></head>
<body>
<div id="footer_content">ArthaNeeti Research Report - Page <pdf:pagenumber/> of <pdf:pagecount/></div>
{header}
{body}
<div class="footer">Generated by ArthaNeeti on {generated}. Grounded in live market data, recent news, and
filed annual reports at the time of the run - see the full cited report for sources and caveats.</div>
</body></html>"""


def render_report_pdf(report: dict) -> bytes:
    buf = io.BytesIO()
    result = pisa.CreatePDF(render_report_html(report), dest=buf)
    if result.err:
        raise RuntimeError(f"PDF generation failed ({result.err} error(s))")
    return buf.getvalue()
