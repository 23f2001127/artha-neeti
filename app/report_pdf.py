"""PDF export of a finished research report.

Laid out with reportlab Platypus. Charts are vector drawings built from
``report["visuals"]`` (the same chart data the web dashboard uses), and the
Inter / Source Serif 4 fonts are embedded so rupee signs and typographic
punctuation render exactly as they do on screen.
"""

from __future__ import annotations

import io
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

from PIL import Image

from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

_ASSETS = Path(__file__).resolve().parents[1] / "assets"

# ---------------------------------------------------------------- fonts

_FONT_FILES = {
    "Inter": "Inter-Regular.ttf",
    "Inter-SemiBold": "Inter-SemiBold.ttf",
    "Inter-Bold": "Inter-Bold.ttf",
    "Serif": "SourceSerif4-SemiBold.ttf",
}
for _name, _file in _FONT_FILES.items():
    pdfmetrics.registerFont(TTFont(_name, str(_ASSETS / "fonts" / _file)))
pdfmetrics.registerFontFamily("Inter", normal="Inter", bold="Inter-Bold", italic="Inter", boldItalic="Inter-Bold")

_GLYPHS = set(pdfmetrics.getFont("Inter").face.charToGlyph)
_CHAR_FALLBACK = {"\u2011": "-", "\u2010": "-", "\u2009": " ", "\u202f": " ", "\u00a0": " ", "\u200b": ""}

# ---------------------------------------------------------------- palette (light theme tokens)

INK = colors.HexColor("#0c1626")
MUTED = colors.HexColor("#4b5568")
FAINT = colors.HexColor("#7f8898")
RULE = colors.HexColor("#dfe2e7")
GRID = colors.HexColor("#eceef1")
PANEL = colors.HexColor("#f5f6f8")
BRAND = colors.HexColor("#9a6b1f")
SINGLE = colors.HexColor("#b8842f")
SINGLE_FILL = colors.Color(184 / 255, 132 / 255, 47 / 255, alpha=0.13)
POSITIVE = colors.HexColor("#1e7a4c")
NEGATIVE = colors.HexColor("#b23a3a")
NEUTRAL = colors.HexColor("#9aa1ad")
CATEGORICAL = [colors.HexColor(c) for c in ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")]
SENTIMENT = {"positive": POSITIVE, "neutral": NEUTRAL, "negative": NEGATIVE}

SPECIALIST_LABEL = {"market_data": "Market data", "news_sentiment": "News & sentiment", "filings": "Annual report"}

# Reports saved before failures moved to report["unavailable"] carry the error in the section text.
_LEGACY_UNAVAILABLE = re.compile(r"not available", re.IGNORECASE)
_LLM_QUOTA_RE = re.compile(r"\bLLM (?:quota|rate)(?: limit)?\b", re.IGNORECASE)
_ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?")

# ---------------------------------------------------------------- page geometry

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
FIRST_TOP = 40 * mm
LATER_TOP = 24 * mm
BOTTOM = 20 * mm
GUTTER = 6 * mm
HALF_W = (CONTENT_W - GUTTER) / 2

# ---------------------------------------------------------------- text styles


def _style(name: str, **kw: Any) -> ParagraphStyle:
    base = {"fontName": "Inter", "fontSize": 9.5, "leading": 14, "textColor": INK}
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    "body": _style("body", spaceAfter=6),
    "lead": _style("lead", fontSize=10.5, leading=16, spaceAfter=8),
    "title": _style("title", fontName="Serif", fontSize=24, leading=29, spaceAfter=4),
    "h1": _style("h1", fontName="Serif", fontSize=19, leading=23, spaceAfter=2),
    "h2": _style("h2", keepWithNext=1, fontName="Serif", fontSize=13.5, leading=17, spaceBefore=12, spaceAfter=6),
    "h3": _style("h3", keepWithNext=1, fontName="Inter-SemiBold", fontSize=10, leading=14, spaceBefore=6, spaceAfter=3),
    "kicker": _style("kicker", keepWithNext=1, fontName="Inter-SemiBold", fontSize=7.5, leading=10, textColor=BRAND, spaceAfter=4),
    "meta": _style("meta", fontSize=8.5, leading=12, textColor=MUTED),
    "small": _style("small", fontSize=8, leading=11, textColor=MUTED),
    "caption": _style("caption", fontSize=7.5, leading=10, textColor=FAINT),
    "chart_title": _style("chart_title", keepWithNext=1, fontName="Inter-SemiBold", fontSize=9, leading=12),
    "chart_sub": _style("chart_sub", keepWithNext=1, fontSize=7.5, leading=10, textColor=FAINT, spaceAfter=4),
    "cell": _style("cell", fontSize=8.5, leading=12),
    "cell_muted": _style("cell_muted", fontSize=8.5, leading=12, textColor=MUTED),
    "cell_head": _style("cell_head", fontName="Inter-SemiBold", fontSize=7.5, leading=10, textColor=MUTED),
    "cell_head_right": _style("cell_head_right", fontName="Inter-SemiBold", fontSize=7.5, leading=10, textColor=MUTED, alignment=TA_RIGHT),
    "cell_right": _style("cell_right", fontSize=8.5, leading=12, alignment=TA_RIGHT),
    "kpi_label": _style("kpi_label", fontSize=7, leading=9, textColor=FAINT),
    "kpi_value": _style("kpi_value", fontName="Inter-SemiBold", fontSize=10.5, leading=14),
    "bullet": _style("bullet", leftIndent=10, bulletIndent=0, spaceAfter=3),
    "note": _style("note", fontSize=8, leading=11.5, textColor=MUTED, spaceAfter=2),
}


def _clean(text: Any) -> str:
    if text is None:
        return ""
    out = []
    for ch in str(text):
        if ch in _CHAR_FALLBACK:
            out.append(_CHAR_FALLBACK[ch])
        elif ord(ch) in _GLYPHS or ch in "\n\t":
            out.append(ch)
    return "".join(out)


def _t(text: Any) -> str:
    """Paragraph-safe markup for plain text."""
    return escape(_clean(text))


def P(text: Any, style: str = "body") -> Paragraph:
    return Paragraph(_t(text), S[style])


def _paragraphs(text: Any, style: str = "body") -> list[Paragraph]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", _clean(text or "")) if p.strip()]
    return [Paragraph(escape(p).replace("\n", "<br/>"), S[style]) for p in parts]


def _bullets(items: list, style: str = "bullet") -> list[Paragraph]:
    return [Paragraph(_t(i), S[style], bulletText="•") for i in items if i]


# ---------------------------------------------------------------- number formatting


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _sym(currency: str | None) -> str:
    return "₹" if not currency or currency == "INR" else f"{currency} "


def fmt_money(v: Any, currency: str | None = "INR") -> str:
    if not _num(v):
        return "—"
    if not currency or currency == "INR":
        if abs(v) >= 1e12:
            return f"₹{v / 1e12:.2f}L Cr"
        if abs(v) >= 1e7:
            return f"₹{v / 1e7:,.0f} Cr"
    return f"{_sym(currency)}{v:,.0f}"


def fmt_price(v: Any, currency: str | None = "INR") -> str:
    return f"{_sym(currency)}{v:,.2f}" if _num(v) else "—"


def fmt_pct(v: Any, signed: bool = False, digits: int = 1) -> str:
    if not _num(v):
        return "—"
    return f"{'+' if signed and v > 0 else ''}{v:.{digits}f}%"


def fmt_x(v: Any, digits: int = 1) -> str:
    return f"{v:.{digits}f}x" if _num(v) else "—"


def fmt_unit(v: Any, unit: str | None) -> str:
    if unit == "%":
        return fmt_pct(v)
    if unit == "x":
        return fmt_x(v)
    return f"{v:,.2f}" if _num(v) else "—"


def fmt_date(value: Any, pattern: str = "%d %b %Y") -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime(pattern).lstrip("0")
    except ValueError:
        return str(value)


def _crore_axis(v: float) -> str:
    c = v / 1e7
    return f"{c / 1e5:.1f}L" if abs(c) >= 1e5 else f"{c:,.0f}"


# ---------------------------------------------------------------- chart primitives


def _nice_ticks(lo: float, hi: float, count: int = 4) -> list[float]:
    if hi == lo:
        pad = abs(hi) * 0.1 or 1
        lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if (hi - lo) / (m * mag) <= count)
    start = math.floor(lo / step) * step
    end = math.ceil(hi / step) * step
    n = int(round((end - start) / step))
    return [round(start + i * step, 10) for i in range(n + 1)]


def _text(d: Drawing, x: float, y: float, s: str, size: float = 6.5, color=FAINT, anchor: str = "start", font: str = "Inter"):
    d.add(String(x, y, _clean(s), fontName=font, fontSize=size, fillColor=color, textAnchor=anchor))


class _Plot:
    """Cartesian frame: horizontal hairline grid and y-axis labels."""

    def __init__(self, width: float, height: float, ticks: list[float], fmt: Callable[[float], str],
                 bottom: float = 14, top: float = 6, right: float = 4):
        self.d = Drawing(width, height)
        label_w = max(pdfmetrics.stringWidth(fmt(t), "Inter", 6.5) for t in ticks)
        self.x0, self.x1 = label_w + 6, width - right
        self.y0, self.y1 = bottom, height - top
        self.lo, self.hi = ticks[0], ticks[-1]
        for t in ticks:
            y = self.y(t)
            self.d.add(Line(self.x0, y, self.x1, y, strokeColor=GRID, strokeWidth=0.6))
            _text(self.d, self.x0 - 4, y - 2.3, fmt(t), anchor="end")
        if self.lo < 0 < self.hi:
            self.d.add(Line(self.x0, self.y(0), self.x1, self.y(0), strokeColor=RULE, strokeWidth=0.9))

    def y(self, v: float) -> float:
        return self.y0 + (v - self.lo) / (self.hi - self.lo) * (self.y1 - self.y0)

    def band(self, i: int, n: int) -> tuple[float, float]:
        w = (self.x1 - self.x0) / n
        return self.x0 + i * w, w

    def x_label(self, x: float, s: str):
        _text(self.d, x, self.y0 - 9, s, anchor="middle")


def _bar(d: Drawing, x: float, w: float, y_base: float, y_top: float, color):
    lo, hi = sorted((y_base, y_top))
    d.add(Rect(x, lo, w, max(hi - lo, 0.4), fillColor=color, strokeColor=None, rx=1.2, ry=1.2))


def _legend(items: list[tuple[str, Any]], line: bool = False) -> Drawing:
    height = 10
    x = 0
    d = Drawing(CONTENT_W, height)
    for label, color in items:
        if line:
            d.add(Line(x, 3.5, x + 9, 3.5, strokeColor=color, strokeWidth=2))
            x += 12
        else:
            d.add(Rect(x, 0.8, 6, 6, fillColor=color, strokeColor=None, rx=1, ry=1))
            x += 9
        _text(d, x, 1.2, label, size=7, color=MUTED)
        x += pdfmetrics.stringWidth(_clean(label), "Inter", 7) + 12
    d.width = x
    return d


def _series_line(plot: _Plot, xs: list[float], ys: list[float], color, width: float = 1.6, dots: bool = False):
    pts: list[float] = []
    for x, y in zip(xs, ys):
        pts += [x, plot.y(y)]
    if len(pts) >= 4:
        plot.d.add(PolyLine(pts, strokeColor=color, strokeWidth=width, strokeLineJoin=1, strokeLineCap=1))
    if dots:
        for x, y in zip(xs, ys):
            plot.d.add(Circle(x, plot.y(y), 2.2, fillColor=color, strokeColor=colors.white, strokeWidth=0.8))


def _month_ticks(dates: list[str], xs: list[float], plot: _Plot, every: int = 2):
    seen = None
    count = 0
    for date, x in zip(dates, xs):
        month = str(date)[:7]
        if month != seen:
            if seen is not None and count % every == 0 and x < plot.x1 - 12:
                plot.x_label(x, fmt_date(date, "%b %y"))
            seen = month
            count += 1


# ---------------------------------------------------------------- charts


def price_chart(history: list[dict], currency: str | None, width: float = CONTENT_W, height: float = 150) -> Drawing | None:
    rows = [r for r in history if _num(r.get("close"))]
    if len(rows) < 2:
        return None
    closes = [r["close"] for r in rows]
    plot = _Plot(width, height, _nice_ticks(min(closes), max(closes)), lambda v: f"{_sym(currency)}{v:,.0f}")
    step = (plot.x1 - plot.x0) / (len(rows) - 1)
    xs = [plot.x0 + i * step for i in range(len(rows))]
    area = [plot.x0, plot.y0]
    for x, c in zip(xs, closes):
        area += [x, plot.y(c)]
    area += [xs[-1], plot.y0]
    plot.d.add(Polygon(area, fillColor=SINGLE_FILL, strokeColor=None))
    _series_line(plot, xs, closes, SINGLE, 1.6)
    plot.d.add(Circle(xs[-1], plot.y(closes[-1]), 2.4, fillColor=SINGLE, strokeColor=colors.white, strokeWidth=0.8))
    _month_ticks([r["date"] for r in rows], xs, plot)
    return plot.d


def returns_chart(returns: dict, width: float = HALF_W, height: float = 118) -> Drawing | None:
    periods = [p for p in ("1M", "3M", "6M", "1Y") if _num(returns.get(p))]
    if not periods:
        return None
    vals = [returns[p] for p in periods]
    plot = _Plot(width, height, _nice_ticks(min(0, *vals) * 1.2, max(0, *vals) * 1.2), lambda v: f"{v:.0f}%", top=12)
    for i, (p, v) in enumerate(zip(periods, vals)):
        x, w = plot.band(i, len(periods))
        bw = min(18, w * 0.5)
        _bar(plot.d, x + (w - bw) / 2, bw, plot.y(0), plot.y(v), POSITIVE if v >= 0 else NEGATIVE)
        label_y = plot.y(v) + 3 if v >= 0 else plot.y(v) - 8
        _text(plot.d, x + w / 2, label_y, fmt_pct(v, signed=True), size=7, color=INK, anchor="middle")
        plot.x_label(x + w / 2, p)
    return plot.d


def financials_chart(fin: list[dict], width: float = HALF_W, height: float = 118) -> Drawing | None:
    rows = [r for r in fin if _num(r.get("revenue"))]
    if not rows:
        return None
    vals = [r["revenue"] for r in rows] + [r["net_income"] for r in rows if _num(r.get("net_income"))]
    plot = _Plot(width, height, _nice_ticks(min(0, *vals), max(vals)), _crore_axis)
    for i, r in enumerate(rows):
        x, w = plot.band(i, len(rows))
        bw = min(14, w * 0.3)
        cx = x + w / 2
        _bar(plot.d, cx - bw - 1, bw, plot.y(0), plot.y(r["revenue"]), CATEGORICAL[0])
        if _num(r.get("net_income")):
            _bar(plot.d, cx + 1, bw, plot.y(0), plot.y(r["net_income"]), CATEGORICAL[1])
        plot.x_label(cx, f"FY{str(r.get('fiscal_year'))[-2:]}")
    return plot.d


def margin_trend_chart(fin: list[dict], width: float = HALF_W, height: float = 118) -> Drawing | None:
    keys = [k for k in ("operating_margin", "net_margin") if sum(_num(r.get(k)) for r in fin) >= 2]
    if not keys:
        return None
    vals = [r[k] for r in fin for k in keys if _num(r.get(k))]
    plot = _Plot(width, height, _nice_ticks(min(0, *vals), max(vals)), lambda v: f"{v:.0f}%")
    centers = [plot.band(i, len(fin))[0] + plot.band(i, len(fin))[1] / 2 for i in range(len(fin))]
    for i, k in enumerate(keys):
        pts = [(c, r[k]) for c, r in zip(centers, fin) if _num(r.get(k))]
        _series_line(plot, [p[0] for p in pts], [p[1] for p in pts], CATEGORICAL[i], 1.6, dots=True)
    for c, r in zip(centers, fin):
        plot.x_label(c, f"FY{str(r.get('fiscal_year'))[-2:]}")
    return plot.d


def hbar_chart(items: list[tuple[str, float, Any]], fmt: Callable[[float], str], width: float = HALF_W,
               bar_h: float = 9, gap: float = 9) -> Drawing | None:
    items = [i for i in items if _num(i[1])]
    if not items:
        return None
    label_w = max(pdfmetrics.stringWidth(_clean(i[0]), "Inter", 7.5) for i in items) + 8
    value_w = max(pdfmetrics.stringWidth(fmt(i[1]), "Inter-SemiBold", 7.5) for i in items) + 6
    height = len(items) * (bar_h + gap) + 2
    d = Drawing(width, height)
    lo = min(0.0, *(i[1] for i in items))
    hi = max(0.0, *(i[1] for i in items))
    span = (hi - lo) or 1e-9
    track = width - label_w - value_w
    zero = label_w + track * (-lo) / span
    for n, (label, value, color) in enumerate(items):
        y = height - (n + 1) * (bar_h + gap) + gap / 2
        _text(d, 0, y + 2, label, size=7.5, color=MUTED)
        d.add(Rect(label_w, y, track, bar_h, fillColor=PANEL, strokeColor=None, rx=1.5, ry=1.5))
        end = label_w + track * (value - lo) / span
        left, right = sorted((zero, end))
        d.add(Rect(left, y, max(right - left, 0.6), bar_h, fillColor=color, strokeColor=None, rx=1.5, ry=1.5))
    if lo < 0 < hi:
        d.add(Line(zero, 0, zero, height - 2, strokeColor=FAINT, strokeWidth=0.6))
    for n, (label, value, color) in enumerate(items):
        y = height - (n + 1) * (bar_h + gap) + gap / 2
        _text(d, width, y + 2, fmt(value), size=7.5, color=INK, anchor="end", font="Inter-SemiBold")
    return d


def relative_chart(series: list[dict], tickers: list[str], width: float = CONTENT_W, height: float = 160) -> Drawing | None:
    if len(series) < 2:
        return None
    vals = [row[t] for row in series for t in tickers if _num(row.get(t))]
    plot = _Plot(width, height, _nice_ticks(min(vals), max(vals)), lambda v: f"{v:.0f}")
    plot.d.add(Line(plot.x0, plot.y(100), plot.x1, plot.y(100), strokeColor=FAINT, strokeWidth=0.7, strokeDashArray=[2, 2]))
    step = (plot.x1 - plot.x0) / (len(series) - 1)
    xs = [plot.x0 + i * step for i in range(len(series))]
    for i, t in enumerate(tickers):
        pts = [(x, row[t]) for x, row in zip(xs, series) if _num(row.get(t))]
        _series_line(plot, [p[0] for p in pts], [p[1] for p in pts], CATEGORICAL[i % 6], 1.6)
    _month_ticks([r["date"] for r in series], xs, plot)
    return plot.d


def sentiment_bar(breakdown: dict, width: float = CONTENT_W, height: float = 12) -> Drawing | None:
    order = ["positive", "neutral", "negative"]
    total = sum(breakdown.get(k) or 0 for k in order)
    if not total:
        return None
    d = Drawing(width, height)
    x = 0.0
    for k in order:
        n = breakdown.get(k) or 0
        if not n:
            continue
        w = width * n / total
        d.add(Rect(x, 0, w - 1.2, height, fillColor=SENTIMENT[k], strokeColor=None))
        x += w
    return d


# ---------------------------------------------------------------- layout helpers


class _Rule(Flowable):
    def __init__(self, width: float = CONTENT_W, color=RULE, thickness: float = 0.6, space: float = 6):
        super().__init__()
        self.width, self.color, self.thickness, self.space = width, color, thickness, space

    def wrap(self, *_):
        return self.width, self.space * 2

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, self.space, self.width, self.space)


def _figure(title: str, subtitle: str | None, drawing: Drawing | None, legend: Drawing | None = None) -> list | None:
    if drawing is None:
        return None
    parts: list = [P(title, "chart_title")]
    if subtitle:
        parts.append(P(subtitle, "chart_sub"))
    if legend is not None:
        parts += [legend, Spacer(1, 5)]
    parts.append(drawing)
    return parts


def _figure_row(left: list | None, right: list | None) -> list:
    if left and right:
        t = Table([[left, right]], colWidths=[HALF_W + GUTTER / 2, HALF_W + GUTTER / 2])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), GUTTER / 2),
            ("LEFTPADDING", (1, 0), (1, 0), GUTTER / 2),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return [KeepTogether([t]), Spacer(1, 14)]
    one = left or right
    return [KeepTogether(one), Spacer(1, 14)] if one else []


def _data_table(header: list[str], rows: list[list], widths: list[float], right_cols: tuple = ()) -> Table:
    data = [[Paragraph(_t(h), S["cell_head_right" if i in right_cols else "cell_head"]) for i, h in enumerate(header)]]
    for row in rows:
        data.append([
            c if isinstance(c, Flowable) else Paragraph(_t(c), S["cell_right" if i in right_cols else "cell"])
            for i, c in enumerate(row)
        ])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
    ]))
    return t


def _kpi_grid(cells: list[tuple[str, str]], columns: int = 6) -> Table:
    rows = []
    for i in range(0, len(cells), columns):
        chunk = cells[i:i + columns]
        chunk += [("", "")] * (columns - len(chunk))
        rows.append([[Paragraph(_t(label), S["kpi_label"]), Paragraph(_t(value), S["kpi_value"])] for label, value in chunk])
    t = Table(rows, colWidths=[CONTENT_W / columns] * columns)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _join_source_fragments(sources: list[str]) -> list[str]:
    out: list[str] = []
    for part in sources:
        if out and out[-1].count("(") > out[-1].count(")"):
            out[-1] = f"{out[-1]}, {part}"
        else:
            out.append(part)
    return out


def _describe_source(source: str) -> str:
    key = re.split(r"[\s(,]", source, maxsplit=1)[0]
    detail = source[len(key):].strip(" ,()").replace("as_of", "as of").strip()
    detail = _ISO_TS_RE.sub(lambda m: fmt_date(m.group(0)), detail)
    label = SPECIALIST_LABEL.get(key, key.replace("_", " ").capitalize())
    return f"{label}, {detail}" if detail else label


# ---------------------------------------------------------------- report sections


def _company_name(ticker: str, report: dict, pack: dict | None) -> str:
    if pack and pack.get("name"):
        return pack["name"]
    names = (report or {}).get("companies") or []
    name = names[0] if names else ticker
    return re.sub(r"\s*\([A-Z0-9&.\-]+\)\s*$", "", name) or ticker


def _kpis(pack: dict) -> list[tuple[str, str]]:
    k = pack.get("kpis") or {}
    cur = pack.get("currency")
    lo, hi = k.get("week52_low"), k.get("week52_high")
    week52 = f"{lo:,.0f} – {hi:,.0f}" if _num(lo) and _num(hi) else "—"
    return [
        ("Share price", fmt_price(k.get("price"), cur)),
        ("Market cap", fmt_money(k.get("market_cap"), cur)),
        ("P/E (TTM)", fmt_x(k.get("pe_ratio"))),
        ("Forward P/E", fmt_x(k.get("forward_pe"))),
        ("EPS (TTM)", fmt_price(k.get("eps_ttm"), cur)),
        ("Dividend yield", fmt_pct(k.get("dividend_yield_pct"), digits=2)),
        ("52-week range", week52),
        ("Return on equity", fmt_pct(k.get("roe"))),
        ("Return on assets", fmt_pct(k.get("roa"))),
        ("Debt to equity", fmt_x(k.get("debt_to_equity"), 2)),
        ("Current ratio", fmt_x(k.get("current_ratio"), 2)),
        ("1-year return", fmt_pct((pack.get("returns") or {}).get("1Y"), signed=True)),
    ]


def _company_charts(pack: dict) -> list:
    story: list = []
    cur = pack.get("currency")
    history = pack.get("price_history") or []
    fin = pack.get("financials") or []
    k = pack.get("kpis") or {}

    if history:
        closes = [r["close"] for r in history if _num(r.get("close"))]
        sub = f"Daily close, {fmt_date(history[0].get('date'))} to {fmt_date(history[-1].get('date'))}"
        if _num(k.get("week52_low")) and _num(k.get("week52_high")):
            sub += f"  ·  52-week range {fmt_price(k['week52_low'], cur)} – {fmt_price(k['week52_high'], cur)}"
        elif closes:
            sub += f"  ·  last {fmt_price(closes[-1], cur)}"
        story += _figure_row(_figure("Share price", sub, price_chart(history, cur)), None)

    growth = None
    revs = [r for r in fin if _num(r.get("revenue")) and r["revenue"] > 0]
    if len(revs) >= 2:
        growth = ((revs[-1]["revenue"] / revs[0]["revenue"]) ** (1 / (len(revs) - 1)) - 1) * 100
    story += _figure_row(
        _figure("Price returns", "Change in share price over each period", returns_chart(pack.get("returns") or {})),
        _figure(
            "Revenue and net profit",
            "₹ crore, annual" + (f"  ·  revenue CAGR {fmt_pct(growth)}" if growth is not None else ""),
            financials_chart(fin),
            _legend([("Revenue", CATEGORICAL[0]), ("Net profit", CATEGORICAL[1])]),
        ),
    )

    m = pack.get("margins") or {}
    profile = [(label, m.get(key), SINGLE) for key, label in
               (("gross", "Gross"), ("ebitda", "EBITDA"), ("operating", "Operating"), ("net", "Net"))]
    story += _figure_row(
        _figure("Margin trend", "Share of revenue, annual", margin_trend_chart(fin),
                _legend([("Operating margin", CATEGORICAL[0]), ("Net margin", CATEGORICAL[1])], line=True)),
        _figure("Profitability", "Latest reported margins", hbar_chart(profile, fmt_pct)),
    )

    senti = pack.get("sentiment")
    if senti and senti.get("breakdown"):
        story += _sentiment_block(senti)
    return story


def _sentiment_block(senti: dict) -> list:
    b = senti["breakdown"]
    total = sum(b.get(k) or 0 for k in ("positive", "neutral", "negative"))
    sub = f"{total} recent article{'s' if total != 1 else ''}"
    if senti.get("as_of"):
        sub += f"  ·  as of {fmt_date(senti['as_of'])}"
    legend = _legend([(f"{k.capitalize()} ({b.get(k) or 0})", SENTIMENT[k]) for k in ("positive", "neutral", "negative")])
    parts = _figure("News sentiment", sub, sentiment_bar(b), legend) or []
    articles = (senti.get("articles") or [])[:6]
    if articles:
        rows = [[(a.get("label") or "neutral").capitalize(), a.get("title") or "", fmt_date(a.get("published_date"))]
                for a in articles]
        parts += [Spacer(1, 8), _data_table(["Tone", "Headline", "Published"], rows, [20 * mm, CONTENT_W - 48 * mm, 28 * mm])]
    return [KeepTogether(parts), Spacer(1, 14)] if parts else []


def _analysis(report: dict) -> list:
    story: list = []
    raw = report.get("sections") or {}
    unavailable = dict(report.get("unavailable") or {})
    sections = {}
    for key in [*SPECIALIST_LABEL, *(k for k in raw if k not in SPECIALIST_LABEL)]:
        text = raw.get(key)
        if not text:
            continue
        if _LEGACY_UNAVAILABLE.match(text):
            unavailable.setdefault(key, "This source could not be retrieved during this run.")
        else:
            sections[key] = text
    if sections:
        story.append(P("Analysis", "h2"))
        for key, text in sections.items():
            paras = _paragraphs(text)
            story.append(KeepTogether([P(SPECIALIST_LABEL.get(key, key), "h3"), *paras[:1]]))
            story += paras[1:]
    missing = [f"{SPECIALIST_LABEL.get(k, k)}: {v}" for k, v in unavailable.items() if v != "Not part of this analysis."]
    if missing:
        story += [P("Not included in this report", "h3"), *_bullets(missing)]
    return story


def _conflicts(conflicts: list) -> list:
    if not conflicts:
        return []
    story: list = [P("Conflicting signals", "h2"),
                   P("Where sources disagreed, both positions are shown with how the report weighed them.", "small"),
                   Spacer(1, 4)]
    label_w = 30 * mm
    for c in conflicts:
        rows = [
            [P(_plain(c.get("specialist_a") or "Source A").capitalize(), "cell_head"), P(c.get("position_a"), "cell")],
            [P(_plain(c.get("specialist_b") or "Source B").capitalize(), "cell_head"), P(c.get("position_b"), "cell")],
            [P("Assessment", "cell_head"), P(c.get("assessment"), "cell")],
        ]
        t = Table(rows, colWidths=[label_w, CONTENT_W - label_w])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(KeepTogether([P(c.get("topic"), "h3"), t, Spacer(1, 6)]))
    return story


def _evidence(sources_by_claim: dict) -> list:
    if not sources_by_claim:
        return []
    story: list = [P("Key findings and sources", "h2")]
    rows = []
    for n, (claim, meta) in enumerate(sources_by_claim.items(), 1):
        meta = meta or {}
        cites = "; ".join(_describe_source(s) for s in _join_source_fragments(meta.get("sources") or [])) or "Unattributed"
        body = [P(claim, "cell"), P(f"Source: {cites}", "note")]
        if meta.get("caveat"):
            body.append(P(f"Note: {meta['caveat']}", "note"))
        rows.append([P(str(n), "cell_muted"), body])
    t = Table(rows, colWidths=[8 * mm, CONTENT_W - 8 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    return story


def _plain(text: Any) -> str:
    """Specialist keys and provider jargon in model prose, in reader terms."""
    out = _LLM_QUOTA_RE.sub("usage limit", str(text))
    for key, label in SPECIALIST_LABEL.items():
        out = re.sub(rf"\b{key}\b", label.lower().replace(" & ", " and "), out)
    return out


def _limitations(caveats: list, missing: list) -> list:
    items = [_plain(i) for i in list(caveats or []) + list(missing or []) if i]
    return [P("Limitations", "h2"), *_bullets(items)] if items else []


def _sector_line(pack: dict | None) -> str:
    return " · ".join(x for x in ((pack or {}).get("sector"), (pack or {}).get("industry")) if x)


def _company_section(ticker: str, report: dict, pack: dict | None, heading: bool = True) -> list:
    name = _company_name(ticker, report, pack)
    story: list = []
    if heading:
        story += [P((_sector_line(pack) or "Company report").upper(), "kicker"), P(f"{name} ({ticker})", "h1"), _Rule(space=5)]

    if not isinstance(report, dict) or report.get("error"):
        story.append(P("This company's analysis could not be completed in this run.", "body"))
        return story

    if report.get("executive_summary"):
        story += _paragraphs(report["executive_summary"], "lead")
    if pack:
        story += [Spacer(1, 4), _kpi_grid(_kpis(pack)), Spacer(1, 14)]
        story += _company_charts(pack)
    story += _analysis(report)
    story += _conflicts(report.get("conflicts_flagged") or [])
    story += _evidence(report.get("sources_by_claim") or {})
    story += _limitations(report.get("overall_caveats"), report.get("missing_data"))
    return story


def _comparison_section(comparison: dict, visuals: dict, tickers: list[str], names: dict[str, str]) -> list:
    story: list = []
    if comparison.get("verdict"):
        story += _paragraphs(comparison["verdict"], "lead")
    vc = (visuals or {}).get("comparison") or {}
    rel = vc.get("relative_performance") or []
    if rel:
        legend = _legend([(names.get(t, t), CATEGORICAL[i % 6]) for i, t in enumerate(tickers)], line=True)
        story += _figure_row(_figure("Relative performance", f"Share price rebased to 100 on {fmt_date(rel[0].get('date'))}",
                                     relative_chart(rel, tickers), legend), None)
    metrics = [m for m in vc.get("metrics") or [] if any(_num(v) for v in (m.get("values") or {}).values())]
    if metrics:
        story += [P("Key metrics side by side", "chart_title"), P("Each metric on its own scale", "chart_sub"),
                  _legend([(t, CATEGORICAL[i % 6]) for i, t in enumerate(tickers)]), Spacer(1, 6)]
        cols = 3
        cell_w = (CONTENT_W - GUTTER * (cols - 1)) / cols
        cells = []
        for m in metrics:
            items = [(t, (m.get("values") or {}).get(t), CATEGORICAL[i % 6]) for i, t in enumerate(tickers)]
            chart = hbar_chart(items, lambda v, u=m.get("unit"): fmt_unit(v, u), width=cell_w, bar_h=7, gap=6)
            cells.append([P(m.get("label"), "cell_head"), Spacer(1, 3), chart] if chart else [P(m.get("label"), "cell_head")])
        grid = [cells[i:i + cols] + [[Spacer(1, 1)]] * (cols - len(cells[i:i + cols])) for i in range(0, len(cells), cols)]
        t = Table(grid, colWidths=[cell_w + GUTTER * (cols - 1) / cols] * cols)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), GUTTER * (cols - 1) / cols),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story += [t, Spacer(1, 6)]
    dims = comparison.get("dimensions") or []
    if dims:
        rows = [[d.get("dimension") or "", d.get("assessment") or "", d.get("edge") or "Even"] for d in dims]
        story += [P("Assessment by dimension", "h2"),
                  _data_table(["Dimension", "Assessment", "Edge"], rows, [30 * mm, CONTENT_W - 62 * mm, 32 * mm])]
    if comparison.get("caveats"):
        story += [P("Comparison caveats", "h3"), *_bullets(comparison["caveats"])]
    return story


def _portfolio_section(portfolio: dict, visuals: dict, names: dict[str, str]) -> list:
    story: list = []
    if portfolio.get("narrative"):
        story += _paragraphs(portfolio["narrative"], "lead")
    story += [Spacer(1, 4), _kpi_grid([
        ("Holdings", str(len(portfolio.get("holdings") or []))),
        ("Sectors", str(len(portfolio.get("sector_allocation_pct") or {}))),
        ("Weighted P/E", fmt_x(portfolio.get("weighted_pe_ratio"))),
        ("Weighted ROE", fmt_pct(portfolio.get("weighted_roe"))),
        ("Weighted dividend yield", fmt_pct(portfolio.get("weighted_dividend_yield_pct"), digits=2)),
    ], columns=5), Spacer(1, 14)]

    holdings = portfolio.get("holdings") or []
    weights = [(h.get("ticker") or "", h.get("weight_pct"), CATEGORICAL[i % 6]) for i, h in enumerate(holdings)]
    sectors = [(s, pct, CATEGORICAL[i % 6]) for i, (s, pct) in enumerate((portfolio.get("sector_allocation_pct") or {}).items())]
    story += _figure_row(
        _figure("Holdings", "Portfolio weight by company", hbar_chart(weights, fmt_pct)),
        _figure("Sector exposure", "Share of the portfolio by sector", hbar_chart(sectors, fmt_pct)),
    )
    if holdings:
        rows = [[f"{names.get(h.get('ticker'), h.get('name') or '')} ({h.get('ticker')})", h.get("sector") or "—",
                 fmt_pct(h.get("weight_pct")), fmt_x(h.get("pe_ratio")), fmt_pct(h.get("roe")),
                 fmt_pct(h.get("dividend_yield_pct"), digits=2)] for h in holdings]
        story += [_data_table(["Company", "Sector", "Weight", "P/E", "ROE", "Div. yield"], rows,
                              [CONTENT_W - 118 * mm, 38 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm], right_cols=(2, 3, 4, 5)),
                  Spacer(1, 6)]
    vc = (visuals or {}).get("comparison") or {}
    rel = vc.get("relative_performance") or []
    tickers = [h.get("ticker") for h in holdings if h.get("ticker")]
    if rel and tickers:
        legend = _legend([(t, CATEGORICAL[i % 6]) for i, t in enumerate(tickers)], line=True)
        story += [Spacer(1, 8)] + _figure_row(
            _figure("Relative performance", f"Share price rebased to 100 on {fmt_date(rel[0].get('date'))}",
                    relative_chart(rel, tickers), legend), None)
    if portfolio.get("diversification"):
        story += [P("Diversification", "h2"), *_paragraphs(portfolio["diversification"])]
    if portfolio.get("concentration_risks"):
        story += [P("Concentration risks", "h2"), *_bullets(portfolio["concentration_risks"])]
    if portfolio.get("caveats"):
        story += [P("Portfolio caveats", "h3"), *_bullets(portfolio["caveats"])]
    return story


def _about(generated: str, as_of: str | None) -> list:
    text = (
        "This report was prepared by ArthaNeeti from three independent sources: live market data for NSE-listed "
        "companies, recent news coverage scored for sentiment, and the companies' filed annual reports. Each "
        "finding is attributed to its source, and disagreements between sources are shown rather than averaged away. "
        "Market data reflects the time of the run; annual-report figures reflect the latest filing available, which "
        "may cover an earlier period."
    )
    stamp = f"Prepared {generated}." + (f" Market data as of {fmt_date(as_of, '%d %b %Y, %H:%M UTC')}." if as_of else "")
    return [
        CondPageBreak(60 * mm),
        P("About this report", "h2"),
        P(text, "small"),
        P(stamp, "small"),
        Spacer(1, 4),
        P("For informational purposes only. This report is not investment advice and should not be relied on as the "
          "sole basis for any investment decision.", "small"),
    ]


# ---------------------------------------------------------------- document shell

_NO_COMPANY_NOTE = (
    "No NSE-listed company could be identified in this question, so no research was run. "
    "Try naming the company or its NSE ticker."
)


def _report_kind(report: dict) -> str:
    if report.get("portfolio"):
        return "Portfolio review"
    if report.get("comparison"):
        return "Company comparison"
    if report.get("mode") == "multi":
        return "Multi-company report"
    if report.get("mode") == "single":
        return "Company report"
    return "Research report"


def _title(report: dict, names: dict[str, str]) -> str:
    tickers = list((report.get("reports") or {}).keys())
    if report.get("portfolio"):
        return "Portfolio review: " + ", ".join(tickers)
    if len(tickers) == 1:
        return f"{names.get(tickers[0], tickers[0])} ({tickers[0]})"
    if tickers:
        return " vs ".join(names.get(t, t) for t in tickers)
    return "Research report"


class _NumberedCanvas(pdfcanvas.Canvas):
    """Defers page output so each footer can print the total page count."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._pages: list[dict] = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("Inter", 7.5)
            self.setFillColor(FAINT)
            self.drawRightString(PAGE_W - MARGIN_X, 11 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _print_image(name: str, height_px: int) -> ImageReader:
    with Image.open(_ASSETS / "brand" / name) as im:
        im = im.convert("RGBA")
        im.thumbnail((im.width * height_px // im.height, height_px), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG", optimize=True)
    out.seek(0)
    return ImageReader(out)


_MARK = _print_image("mark.png", 240)
_WORDMARK = _print_image("wordmark.png", 120)


def _draw_brand(c: pdfcanvas.Canvas, x: float, y: float, height: float, with_wordmark: bool = True) -> float:
    mark = _MARK
    mw, mh = mark.getSize()
    w = height * mw / mh
    c.drawImage(mark, x, y, width=w, height=height, mask="auto")
    x += w + height * 0.25
    if with_wordmark:
        word = _WORDMARK
        ww, wh = word.getSize()
        wh_target = height * 0.52
        c.drawImage(word, x, y + (height - wh_target) / 2, width=wh_target * ww / wh, height=wh_target, mask="auto")
        x += wh_target * ww / wh
    return x


def _build_doc(buf: io.BytesIO, title: str, subject: str, generated: str) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=LATER_TOP, bottomMargin=BOTTOM,
        title=_clean(title), author="ArthaNeeti", subject=_clean(subject), creator="ArthaNeeti",
    )

    def footer(c: pdfcanvas.Canvas):
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.line(MARGIN_X, 15 * mm, PAGE_W - MARGIN_X, 15 * mm)
        c.setFont("Inter", 7.5)
        c.setFillColor(FAINT)
        c.drawString(MARGIN_X, 11 * mm, f"ArthaNeeti  ·  {generated}  ·  Not investment advice")

    def first_page(c: pdfcanvas.Canvas, _doc):
        c.saveState()
        top = PAGE_H - 14 * mm
        _draw_brand(c, MARGIN_X, top - 11 * mm, 11 * mm)
        c.setFont("Inter-SemiBold", 8)
        c.setFillColor(INK)
        c.drawRightString(PAGE_W - MARGIN_X, top - 4 * mm, "Equity Research")
        c.setFont("Inter", 8)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE_W - MARGIN_X, top - 8.5 * mm, generated)
        c.setStrokeColor(INK)
        c.setLineWidth(0.8)
        c.line(MARGIN_X, top - 15 * mm, PAGE_W - MARGIN_X, top - 15 * mm)
        footer(c)
        c.restoreState()

    def later_page(c: pdfcanvas.Canvas, _doc):
        c.saveState()
        top = PAGE_H - 10 * mm
        _draw_brand(c, MARGIN_X, top - 5.5 * mm, 5.5 * mm, with_wordmark=False)
        c.setFont("Inter-SemiBold", 7.5)
        c.setFillColor(INK)
        c.drawString(MARGIN_X + 8 * mm, top - 3.6 * mm, "ArthaNeeti")
        c.setFont("Inter", 7.5)
        c.setFillColor(MUTED)
        label = _clean(title)
        max_w = CONTENT_W - 40 * mm
        while pdfmetrics.stringWidth(label, "Inter", 7.5) > max_w and len(label) > 4:
            label = label[:-2]
        c.drawRightString(PAGE_W - MARGIN_X, top - 3.6 * mm, label if label == _clean(title) else label.rstrip() + "…")
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.line(MARGIN_X, top - 7.5 * mm, PAGE_W - MARGIN_X, top - 7.5 * mm)
        footer(c)
        c.restoreState()

    frame_h_first = PAGE_H - FIRST_TOP - BOTTOM
    frame_h_later = PAGE_H - LATER_TOP - BOTTOM
    doc.addPageTemplates([
        PageTemplate("first", [Frame(MARGIN_X, BOTTOM, CONTENT_W, frame_h_first, 0, 0, 0, 0, id="f1")], onPage=first_page),
        PageTemplate("later", [Frame(MARGIN_X, BOTTOM, CONTENT_W, frame_h_later, 0, 0, 0, 0, id="f2")], onPage=later_page),
    ])
    return doc


def render_report_pdf(report: dict) -> bytes:
    generated = datetime.now(timezone.utc).strftime("%d %B %Y").lstrip("0")
    visuals = report.get("visuals") or {}
    packs = visuals.get("companies") or {}
    reports = report.get("reports") or {}
    tickers = list(reports.keys())
    names = {t: _company_name(t, reports.get(t) or {}, packs.get(t)) for t in tickers}
    title = _title(report, names)

    single = len(tickers) == 1 and not report.get("portfolio") and not report.get("comparison")
    kicker = _report_kind(report)
    if single and _sector_line(packs.get(tickers[0])):
        kicker += " · " + _sector_line(packs.get(tickers[0]))
    story: list = [NextPageTemplate("later"), P(kicker.upper(), "kicker"), P(title, "title")]
    if report.get("query"):
        story.append(P(f"Research question: “{_clean(report['query']).strip()}”", "meta"))
    story += [Spacer(1, 6), _Rule(space=5)]

    if report.get("mode") in (None, "none") or not reports:
        story += _paragraphs(_NO_COMPANY_NOTE, "lead")
    else:
        lead_section = False
        if report.get("portfolio"):
            story += _portfolio_section(report["portfolio"], visuals, names)
            lead_section = True
        elif report.get("comparison"):
            story += _comparison_section(report["comparison"], visuals, tickers, names)
            lead_section = True
        for i, t in enumerate(tickers):
            if lead_section or i > 0:
                story.append(PageBreak())
            story += _company_section(t, reports[t], packs.get(t), heading=not single)

    story += _about(generated, visuals.get("as_of"))

    buf = io.BytesIO()
    doc = _build_doc(buf, title, report.get("query") or title, generated)
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
