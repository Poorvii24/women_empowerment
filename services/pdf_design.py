"""
services/pdf_design.py
======================
Reusable, presentation-only component library for the Career Intelligence
Portfolio PDF.

This module knows nothing about Flask, the database, or scoring logic — it
only draws things. All data (scores, gaps, opportunities, growth series...)
is computed elsewhere by the existing engines and passed in here as plain
dicts / dataclasses.

Built on fpdf2 (the library already used across the app for Unicode-aware
PDF generation — see app.py's _register_unicode_fonts / _set_script_aware_font).
ReportLab is not a dependency of this project, so rather than introduce a
second PDF stack, this module raises fpdf2 itself to a component-based,
card/KPI/timeline/chart design system: every drawing primitive below is a
small reusable "widget" (card, KPI tile, progress bar, badge, circular gauge,
donut, radar, bar sparkline, timeline node) that the page-builders in app.py
compose together, instead of the old approach of sequential cell()/multi_cell()
calls styled inline.

Font note: all text helpers use _set_script_aware_font (imported lazily from
app.py at call time to avoid a circular import) so Hindi/Kannada bullet text
keeps rendering correctly, exactly as it did before this redesign.
"""
import math

# ── Design tokens ────────────────────────────────────────────────────────────

INDIGO   = (99, 102, 241)
INDIGO_D = (67, 56, 202)
PINK     = (236, 72, 153)
GREEN    = (16, 185, 129)
AMBER    = (245, 158, 11)
BLUE     = (59, 130, 246)
RED      = (239, 68, 68)

INK      = (30, 41, 59)     # primary text
MUTED    = (100, 116, 139)  # secondary text
FAINT    = (148, 163, 184)  # tertiary / captions
BORDER   = (226, 232, 240)  # hairline strokes
SURFACE  = (248, 250, 252)  # card background
SURFACE2 = (241, 245, 249)  # alt track background
WHITE    = (255, 255, 255)

PAGE_W, PAGE_H = 210, 297
MARGIN = 16
CONTENT_W = PAGE_W - 2 * MARGIN

_FONT = "NotoSans"


def tier_color(pct):
    """Standard 3-tier semantic color for any 0-100 metric."""
    if pct >= 75:
        return GREEN
    if pct >= 50:
        return AMBER
    return RED


# ── Low-level primitives ─────────────────────────────────────────────────────

def set_fill(pdf, rgb):
    pdf.set_fill_color(*rgb)


def set_text(pdf, rgb):
    pdf.set_text_color(*rgb)


def set_draw(pdf, rgb):
    pdf.set_draw_color(*rgb)


def font(pdf, style="", size=10):
    pdf.set_font(_FONT, style, size)


def text_w(pdf, txt):
    return pdf.get_string_width(txt)


_GLYPH_FALLBACKS = {
    "\u2192": "->",   # → not in the bundled NotoSans subset
    "\u2190": "<-",
    "\u25CF": "\u2022",  # ● -> • (supported)
    "\u25AA": "\u2022",  # ▪ -> •
    "\u2713": "OK",   # ✓ not in the bundled subset
    "\u2714": "OK",   # ✔
    "\u2192\ufe0f": "->",
}


def sanitize_text(txt):
    """
    Swaps characters that aren't in the bundled NotoSans glyph subset for
    safe equivalents. Static content dictionaries (role opportunities,
    learning resources, etc.) occasionally contain arrows or check-glyphs
    that this particular font subset doesn't cover — this keeps every page
    free of tofu boxes without touching the underlying data.
    """
    if not txt:
        return txt
    for bad, good in _GLYPH_FALLBACKS.items():
        if bad in txt:
            txt = txt.replace(bad, good)
    return txt


def truncate(pdf, txt, max_w):
    """Shrinks txt with a trailing ellipsis so it fits max_w at the current font."""
    txt = sanitize_text(txt)
    if text_w(pdf, txt) <= max_w:
        return txt
    ell = "..."
    lo, hi = 0, len(txt)
    while lo < hi:
        mid = (lo + hi) // 2
        if text_w(pdf, txt[:mid] + ell) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    return txt[:max(0, lo - 1)] + ell


# ── Page chrome ───────────────────────────────────────────────────────────────

def new_page(pdf):
    pdf.add_page()


def page_footer(pdf, label):
    """
    Draws the footer strip. This is meant to run from inside the FPDF.footer()
    hook (see PortfolioPDF in app.py) — fpdf2 only disables its auto-page-break
    guard while self.in_footer is True, so calling this directly mid-page-build
    at y=-14 would itself trigger a spurious extra page.
    """
    pdf.set_y(-14)
    set_draw(pdf, BORDER)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
    font(pdf, "I", 7.5)
    set_text(pdf, FAINT)
    pdf.set_y(-11)
    pdf.cell(CONTENT_W / 2, 5, "ISIS Career Intelligence Platform", ln=False)
    pdf.set_x(MARGIN + CONTENT_W / 2)
    pdf.cell(CONTENT_W / 2, 5, label, align="R")


def section_title(pdf, text, accent=INDIGO, subtitle=None):
    """Large section heading with a colored accent tab — replaces the old
    solid-fill banner cell with a lighter, more editorial mark."""
    y = pdf.get_y()
    set_fill(pdf, accent)
    pdf.rect(MARGIN, y + 1, 3, 7, "F")
    pdf.set_xy(MARGIN + 6, y)
    font(pdf, "B", 14)
    set_text(pdf, INK)
    pdf.cell(CONTENT_W - 6, 9, text, ln=True)
    if subtitle:
        pdf.set_x(MARGIN + 6)
        font(pdf, "", 9)
        set_text(pdf, MUTED)
        pdf.cell(CONTENT_W - 6, 5.5, subtitle, ln=True)
    pdf.ln(2)


def divider(pdf, gap_before=2, gap_after=3):
    pdf.ln(gap_before)
    set_draw(pdf, BORDER)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
    pdf.ln(gap_after)


# ── Cards & badges ────────────────────────────────────────────────────────────

def card_bg(pdf, x, y, w, h, fill=SURFACE, border=BORDER, radius=3):
    set_fill(pdf, fill)
    set_draw(pdf, border)
    pdf.set_line_width(0.25)
    pdf.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=radius)


def badge(pdf, x, y, txt, color, filled=True):
    """Small pill-shaped label. Returns the width consumed."""
    font(pdf, "B", 7.5)
    w = text_w(pdf, txt) + 6
    h = 5.4
    if filled:
        set_fill(pdf, color)
        pdf.rect(x, y, w, h, style="F", round_corners=True, corner_radius=h / 2)
        set_text(pdf, WHITE)
    else:
        set_draw(pdf, color)
        pdf.set_line_width(0.3)
        pdf.rect(x, y, w, h, style="D", round_corners=True, corner_radius=h / 2)
        set_text(pdf, color)
    pdf.set_xy(x, y + 1.15)
    pdf.cell(w, h - 2, txt, align="C")
    return w


def kpi_grid(pdf, items, cols=3, y=None, card_h=28):
    """
    items: list of dicts {label, value_str, color, sub (optional)}
    Renders a responsive grid of KPI cards.
    """
    if y is None:
        y = pdf.get_y()
    gap = 4
    card_w = (CONTENT_W - gap * (cols - 1)) / cols
    for i, item in enumerate(items):
        col = i % cols
        row = i // cols
        x = MARGIN + col * (card_w + gap)
        cy = y + row * (card_h + gap)
        card_bg(pdf, x, cy, card_w, card_h)
        color = item.get("color", INDIGO)
        set_fill(pdf, color)
        pdf.rect(x, cy, 2.2, card_h, style="F", round_corners=True, corner_radius=1)
        pdf.set_xy(x + 6, cy + 4)
        font(pdf, "B", 15)
        set_text(pdf, color)
        pdf.cell(card_w - 10, 8, item["value_str"], ln=False)
        pdf.set_xy(x + 6, cy + 13.5)
        font(pdf, "B", 8)
        set_text(pdf, INK)
        pdf.multi_cell(card_w - 10, 4, truncate(pdf, item["label"], card_w - 10))
        if item.get("sub"):
            pdf.set_xy(x + 6, cy + card_h - 6.5)
            font(pdf, "", 6.8)
            set_text(pdf, MUTED)
            pdf.cell(card_w - 10, 4, truncate(pdf, item["sub"], card_w - 10))
    rows = math.ceil(len(items) / cols)
    pdf.set_xy(MARGIN, y + rows * (card_h + gap))


def progress_bar(pdf, x, y, w, pct, color, track=SURFACE2, h=3.2):
    set_fill(pdf, track)
    pdf.rect(x, y, w, h, style="F", round_corners=True, corner_radius=h / 2)
    fw = max(h, w * max(0, min(100, pct)) / 100)
    set_fill(pdf, color)
    pdf.rect(x, y, fw, h, style="F", round_corners=True, corner_radius=h / 2)


def metric_row(pdf, label, value, color, explanation=None, sub_label=None):
    """One labeled progress row: label — value% — bar — optional caption."""
    font(pdf, "B", 9.5)
    set_text(pdf, INK)
    pdf.cell(52, 6, label, ln=False)
    font(pdf, "B", 9.5)
    set_text(pdf, color)
    pdf.cell(14, 6, f"{value:.0f}%", ln=False)
    bx, by = pdf.get_x(), pdf.get_y() + 1.4
    bw = CONTENT_W - 52 - 14
    progress_bar(pdf, bx, by, bw, value, color)
    pdf.ln(7.5)
    if sub_label:
        font(pdf, "", 7.5)
        set_text(pdf, FAINT)
        pdf.cell(CONTENT_W, 4, sub_label, ln=True)
    if explanation:
        pdf.set_x(MARGIN)
        font(pdf, "I", 8)
        set_text(pdf, MUTED)
        pdf.multi_cell(CONTENT_W, 4.6, truncate(pdf, explanation, CONTENT_W * 4))
    pdf.ln(1.5)


# ── Circular gauge (cover-page hero score) ───────────────────────────────────

def circular_gauge(pdf, cx, cy, diameter, pct, color, label_top, value_size=30):
    """Ring gauge: light track circle + colored progress arc + centered value."""
    r = diameter
    x0 = cx - r / 2
    y0 = cy - r / 2
    set_draw(pdf, (255, 255, 255))
    pdf.set_line_width(4.2)
    pdf.ellipse(x0, y0, r, r, style="D")
    sweep = max(1, 359.9 * max(0, min(100, pct)) / 100)
    set_draw(pdf, color)
    pdf.set_line_width(4.2)
    pdf.arc(x0, y0, r, -90, -90 + sweep, clockwise=False, style="D")
    font(pdf, "B", value_size)
    set_text(pdf, WHITE)
    pdf.set_xy(cx - r / 2, cy - value_size * 0.42)
    pdf.cell(r, value_size * 0.85, f"{pct:.0f}", align="C")
    font(pdf, "", 8.5)
    pdf.set_xy(cx - r / 2, cy + value_size * 0.34)
    pdf.cell(r, 5, label_top, align="C")


# ── Donut chart ───────────────────────────────────────────────────────────────

DONUT_PALETTE = [INDIGO, GREEN, AMBER, PINK, BLUE, RED, (14, 165, 233), (168, 85, 247)]


def donut_chart(pdf, cx, cy, diameter, segments, thickness=9):
    """
    segments: list of (label, value) — values are relative weights, need not sum to 100.
    Draws a ring chart plus a compact legend to the right.
    """
    total = sum(v for _, v in segments) or 1
    r = diameter
    x0, y0 = cx - r / 2, cy - r / 2
    set_draw(pdf, SURFACE2)
    pdf.set_line_width(thickness)
    pdf.ellipse(x0, y0, r, r, style="D")
    start = -90
    for i, (_, v) in enumerate(segments):
        sweep = 359.9 * v / total
        if sweep <= 0:
            continue
        color = DONUT_PALETTE[i % len(DONUT_PALETTE)]
        set_draw(pdf, color)
        pdf.set_line_width(thickness)
        pdf.arc(x0, y0, r, start, start + sweep, clockwise=False, style="D")
        start += sweep

    legend_x = cx + r / 2 + 10
    legend_y = cy - (len(segments) * 6.2) / 2
    font(pdf, "", 8.5)
    for i, (lbl, v) in enumerate(segments):
        color = DONUT_PALETTE[i % len(DONUT_PALETTE)]
        set_fill(pdf, color)
        pdf.rect(legend_x, legend_y + i * 6.2, 3.4, 3.4, style="F", round_corners=True, corner_radius=1)
        set_text(pdf, INK)
        pdf.set_xy(legend_x + 5.5, legend_y + i * 6.2 - 1.1)
        pct = round(v / total * 100)
        pdf.cell(48, 5, f"{truncate(pdf, lbl, 34)}  ({pct}%)")


# ── Radar chart ───────────────────────────────────────────────────────────────

def radar_chart(pdf, cx, cy, radius, axes):
    """
    axes: list of (label, value 0-100, color) — color used only for the label text.
    Draws a 5(+)-axis radar with two grid rings and a filled polygon.
    """
    n = len(axes)
    if n < 3:
        return
    angle_step = 2 * math.pi / n
    start_angle = -math.pi / 2

    def point(idx, frac):
        ang = start_angle + idx * angle_step
        return cx + radius * frac * math.cos(ang), cy + radius * frac * math.sin(ang)

    # grid rings
    set_draw(pdf, BORDER)
    pdf.set_line_width(0.2)
    for frac in (0.33, 0.66, 1.0):
        pts = [point(i, frac) for i in range(n)]
        pdf.polygon(pts, fill=False, style="D")
    # spokes
    for i in range(n):
        x1, y1 = point(i, 0)
        x2, y2 = point(i, 1.0)
        pdf.line(x1, y1, x2, y2)

    # data polygon
    data_pts = [point(i, max(0.04, v / 100)) for i, (_, v, _) in enumerate(axes)]
    with pdf.local_context(fill_opacity=0.22):
        set_fill(pdf, INDIGO)
        pdf.polygon(data_pts, fill=True, style="F")
    set_draw(pdf, INDIGO_D)
    pdf.set_line_width(0.6)
    pdf.polygon(data_pts, fill=False, style="D")
    for (x, y) in data_pts:
        set_fill(pdf, INDIGO_D)
        pdf.ellipse(x - 1, y - 1, 2, 2, style="F")

    # labels
    font(pdf, "B", 7.8)
    for i, (lbl, v, color) in enumerate(axes):
        lx, ly = point(i, 1.24)
        set_text(pdf, color)
        w = text_w(pdf, lbl)
        pdf.set_xy(lx - w / 2, ly - 2.2)
        pdf.cell(w, 4.4, lbl, align="C")


# ── Bar sparkline (weekly activity / growth trend) ──────────────────────────

def bar_sparkline(pdf, x, y, w, h, values, color, labels=None):
    """Simple bottom-anchored bar chart for a short time series."""
    if not values:
        font(pdf, "I", 8)
        set_text(pdf, FAINT)
        pdf.set_xy(x, y + h / 2 - 3)
        pdf.cell(w, 6, "Not enough activity data yet", align="C")
        return
    vmax = max(values) or 1
    n = len(values)
    gap = 1.6
    bw = (w - gap * (n - 1)) / n
    set_draw(pdf, BORDER)
    pdf.set_line_width(0.2)
    pdf.line(x, y + h, x + w, y + h)
    for i, v in enumerate(values):
        bh = max(1.2, (v / vmax) * (h - 3))
        bx = x + i * (bw + gap)
        by = y + h - bh
        set_fill(pdf, color)
        pdf.rect(bx, by, bw, bh, style="F", round_corners=True, corner_radius=min(1, bw / 3))
    if labels:
        font(pdf, "", 6.2)
        set_text(pdf, FAINT)
        pdf.set_xy(x, y + h + 1.2)
        step = max(1, n // 6)
        for i in range(0, n, step):
            bx = x + i * (bw + gap)
            pdf.set_xy(bx, y + h + 1.2)
            pdf.cell(bw * step, 3.5, labels[i], align="C")


def line_trend(pdf, x, y, w, h, values, color):
    """Thin line + area trend for skill-growth over time."""
    if not values or len(values) < 2:
        font(pdf, "I", 8)
        set_text(pdf, FAINT)
        pdf.set_xy(x, y + h / 2 - 3)
        pdf.cell(w, 6, "Not enough history yet to chart growth", align="C")
        return
    vmin, vmax = min(values), max(values)
    span = (vmax - vmin) or 1
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        px = x + (w * i / (n - 1))
        py = y + h - ((v - vmin) / span) * h
        pts.append((px, py))
    set_draw(pdf, BORDER)
    pdf.set_line_width(0.2)
    pdf.line(x, y + h, x + w, y + h)
    set_draw(pdf, color)
    pdf.set_line_width(0.8)
    for i in range(len(pts) - 1):
        pdf.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
    for (px, py) in pts:
        set_fill(pdf, color)
        pdf.ellipse(px - 1.1, py - 1.1, 2.2, 2.2, style="F")


# ── Timeline (30/60/90 roadmap) ──────────────────────────────────────────────

def timeline_phase(pdf, title, sub, color, items, icon_char="\u2022"):
    """One phase block of the roadmap: colored header pill + connected item nodes."""
    y = pdf.get_y()
    set_fill(pdf, color)
    pdf.rect(MARGIN, y, CONTENT_W, 9, style="F", round_corners=True, corner_radius=2)
    set_text(pdf, WHITE)
    font(pdf, "B", 10.5)
    pdf.set_xy(MARGIN + 4, y + 1.3)
    pdf.cell(CONTENT_W - 8, 6.5, title, ln=False)
    font(pdf, "", 8)
    pdf.set_xy(MARGIN, y + 1.6)
    tw = text_w(pdf, sub) + 4
    pdf.set_xy(MARGIN + CONTENT_W - tw - 4, y + 1.8)
    pdf.cell(tw, 6, sub, align="R")
    pdf.set_xy(MARGIN, y + 11)

    rail_x = MARGIN + 5
    for idx, item in enumerate(items):
        row_y = pdf.get_y()
        set_draw(pdf, color)
        pdf.set_line_width(0.6)
        if idx < len(items) - 1:
            pdf.line(rail_x, row_y + 3, rail_x, row_y + 15)
        set_fill(pdf, color)
        pdf.ellipse(rail_x - 1.6, row_y + 1.4, 3.2, 3.2, style="F")

        tx = rail_x + 7
        tw_avail = CONTENT_W - (tx - MARGIN)
        pdf.set_xy(tx, row_y)
        font(pdf, "B", 9)
        set_text(pdf, INK)
        pdf.multi_cell(tw_avail, 5, truncate(pdf, item.get("skill", ""), tw_avail * 3))
        if item.get("why"):
            pdf.set_xy(tx, pdf.get_y())
            font(pdf, "", 7.8)
            set_text(pdf, MUTED)
            pdf.multi_cell(tw_avail, 4.2, truncate(pdf, item["why"], tw_avail * 4))
        if item.get("resource"):
            pdf.set_xy(tx, pdf.get_y())
            font(pdf, "I", 7.5)
            set_text(pdf, color)
            pdf.multi_cell(tw_avail, 4.2, truncate(pdf, "Resource: " + item["resource"], tw_avail * 4))
        pdf.ln(1.6)
    pdf.ln(3)


# ── Recommendation card (projects / hackathons / certs / OSS) ──────────────

def recommendation_card(pdf, x, y, w, h, title, meta_lines, color, tag=None):
    card_bg(pdf, x, y, w, h)
    set_fill(pdf, color)
    pdf.rect(x, y, w, 2.6, style="F", round_corners=True, corner_radius=1.3)
    pdf.set_xy(x + 4, y + 5)
    font(pdf, "B", 9.5)
    set_text(pdf, INK)
    pdf.multi_cell(w - 8, 4.6, truncate(pdf, title, (w - 8) * 3))
    pdf.set_x(x + 4)
    font(pdf, "", 7.8)
    set_text(pdf, MUTED)
    for line in meta_lines:
        pdf.set_x(x + 4)
        pdf.multi_cell(w - 8, 4.2, truncate(pdf, line, (w - 8) * 4))
    # Tag badge pinned to the bottom-right corner — placed last, after the
    # title/meta text has already been laid out, so a long wrapped title can
    # never run underneath and collide with it.
    if tag:
        font(pdf, "B", 7.5)
        tag_w = text_w(pdf, tag) + 6
        badge(pdf, x + w - 4 - tag_w, y + h - 9.4, tag, color)


def recommendation_grid(pdf, cards, cols=2, card_h=32, y=None):
    if y is None:
        y = pdf.get_y()
    gap = 4
    w = (CONTENT_W - gap * (cols - 1)) / cols
    for i, c in enumerate(cards):
        col, row = i % cols, i // cols
        x = MARGIN + col * (w + gap)
        cy = y + row * (card_h + gap)
        recommendation_card(pdf, x, cy, w, card_h, c["title"], c["meta"], c["color"], c.get("tag"))
    rows = math.ceil(len(cards) / cols)
    pdf.set_xy(MARGIN, y + rows * (card_h + gap))


# ── Checklist rows (recruiter snapshot) ──────────────────────────────────────

def checklist_row(pdf, x, y, w, label, done):
    """Draws one checklist row at an explicit (x, y, w) — needed so multi-column
    checklists don't all collapse onto the left margin."""
    color = GREEN if done else FAINT
    set_fill(pdf, color)
    pdf.ellipse(x + 0.5, y + 1.3, 3.4, 3.4, style="F")
    font(pdf, "" if done else "I", 9.5)
    set_text(pdf, INK if done else FAINT)
    pdf.set_xy(x + 7, y)
    pdf.cell(w - 7, 6, truncate(pdf, label, w - 7), ln=False)


# ── Professional Portfolio brochure components ───────────────────────────────
# (Added for the recruiter-facing "Professional Portfolio" — distinct from the
#  analytics-oriented Career Intelligence Report, which uses the components
#  above this point unchanged.)

def numbered_footer(pdf, label):
    """Footer variant with a page-number badge. Uses fpdf2's {nb} alias for the
    total page count (call pdf.alias_nb_pages() once after construction) so
    that if any section overflows onto an extra physical page, the numbering
    stays accurate instead of a hardcoded total going out of sync."""
    pdf.set_y(-14)
    set_draw(pdf, BORDER)
    pdf.set_line_width(0.2)
    pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
    font(pdf, "I", 7.5)
    set_text(pdf, FAINT)
    pdf.set_y(-11)
    pdf.cell(CONTENT_W / 2, 5, label, ln=False)
    pdf.set_x(MARGIN + CONTENT_W / 2)
    pdf.cell(CONTENT_W / 2 - 16, 5, "ISIS Professional Portfolio", align="R")
    font(pdf, "B", 7.5)
    set_text(pdf, INDIGO)
    pdf.cell(16, 5, f"{pdf.page_no()}/{{nb}}", align="R")


def pill_chip(pdf, x, y, txt, color, filled=True):
    """Alias of badge() kept separate so brochure call-sites read clearly."""
    return badge(pdf, x, y, txt, color, filled=filled)


def chip_row(pdf, x, y, w, items, color, filled=True, line_h=8):
    """Wraps a list of short strings into pill chips across width w, returns
    the y position just below the last row."""
    cx, cy = x, y
    for txt in items:
        font(pdf, "B", 7.5)
        cw = text_w(pdf, txt) + 6
        if cx + cw > x + w:
            cx = x
            cy += line_h
        pill_chip(pdf, cx, cy, txt, color, filled=filled)
        cx += cw + 3
    return cy + line_h


def hero_band(pdf, h, color1=INDIGO, color2=INDIGO_D):
    """Full-bleed colored band at the top of a page (subtle two-tone via a
    darker overlay circle), used for cover/section-divider style pages."""
    set_fill(pdf, color1)
    pdf.rect(0, 0, PAGE_W, h, "F")
    set_fill(pdf, color2)
    with pdf.local_context(fill_opacity=0.35):
        pdf.ellipse(PAGE_W - 60, -30, 120, 120, style="F")


def profile_card(pdf, x, y, w, h, title, body_lines, color):
    """Small card used for 'About Me' style tiles (strengths, highlights...)."""
    card_bg(pdf, x, y, w, h)
    set_fill(pdf, color)
    pdf.rect(x, y, w, 2.4, "F", round_corners=True, corner_radius=1.2)
    pdf.set_xy(x + 4, y + 5)
    font(pdf, "B", 9.5)
    set_text(pdf, INK)
    pdf.multi_cell(w - 8, 4.8, truncate(pdf, title, (w - 8) * 3))
    pdf.set_x(x + 4)
    font(pdf, "", 8)
    set_text(pdf, MUTED)
    for line in body_lines:
        pdf.set_x(x + 4)
        pdf.multi_cell(w - 8, 4.2, truncate(pdf, line, (w - 8) * 4))


def skill_bar_group(pdf, category_title, skills, color, icon_dot=True):
    """
    category_title: str
    skills: list of (name, pct) — pct is a 0-100 "prominence" bar length.
    """
    hy = pdf.get_y()
    if icon_dot:
        set_fill(pdf, color)
        pdf.ellipse(MARGIN + 0.8, hy + 1.8, 3, 3, style="F")
    pdf.set_xy(MARGIN + 6, hy)
    font(pdf, "B", 10.5)
    set_text(pdf, INK)
    pdf.cell(CONTENT_W - 6, 6, category_title, ln=True)
    pdf.ln(1)
    for name, pct in skills:
        font(pdf, "", 8.8)
        set_text(pdf, INK)
        pdf.cell(50, 5.6, truncate(pdf, name, 48), ln=False)
        bx = pdf.get_x()
        by = pdf.get_y() + 1
        bw = CONTENT_W - 50
        progress_bar(pdf, bx, by, bw, pct, color)
        pdf.ln(7)
    pdf.ln(2)


def project_card(pdf, x, y, w, h, title, description, tech_tags, color, index=None):
    """Featured-project card: colored spine, title, description, tech chips."""
    card_bg(pdf, x, y, w, h)
    set_fill(pdf, color)
    pdf.rect(x, y, 2.4, h, "F", round_corners=True, corner_radius=1.2)
    pdf.set_xy(x + 6, y + 4)
    font(pdf, "B", 10.5)
    set_text(pdf, INK)
    label = f"{title}"
    pdf.multi_cell(w - 11, 5, truncate(pdf, label, (w - 11) * 2.4))
    pdf.set_x(x + 6)
    font(pdf, "", 8.2)
    set_text(pdf, MUTED)
    pdf.multi_cell(w - 11, 4.3, truncate(pdf, description, (w - 11) * 5))
    if tech_tags:
        cy = y + h - 10
        cx = x + 6
        for tag in tech_tags[:5]:
            font(pdf, "B", 6.8)
            cw = text_w(pdf, tag) + 5
            if cx + cw > x + w - 6:
                break
            pill_chip(pdf, cx, cy, tag, color, filled=False)
            cx += cw + 2.5


def project_grid(pdf, cards, cols=1, card_h=38, y=None, gap=4):
    if y is None:
        y = pdf.get_y()
    w = (CONTENT_W - gap * (cols - 1)) / cols
    for i, c in enumerate(cards):
        col, row = i % cols, i // cols
        x = MARGIN + col * (w + gap)
        cy = y + row * (card_h + gap)
        project_card(pdf, x, cy, w, card_h, c["title"], c["description"], c["tech"], c["color"])
    rows = math.ceil(len(cards) / cols)
    pdf.set_xy(MARGIN, y + rows * (card_h + gap))


def achievement_item(pdf, date_str, title, tag_text, tag_color, subtitle=None, is_last=False):
    """One entry in the Achievements & Experience timeline."""
    row_y = pdf.get_y()
    rail_x = MARGIN + 5
    set_draw(pdf, tag_color)
    pdf.set_line_width(0.6)
    if not is_last:
        pdf.line(rail_x, row_y + 3, rail_x, row_y + 17)
    set_fill(pdf, tag_color)
    pdf.ellipse(rail_x - 1.6, row_y + 1.2, 3.2, 3.2, style="F")

    tx = rail_x + 7
    tw_avail = CONTENT_W - (tx - MARGIN)
    font(pdf, "", 7.3)
    set_text(pdf, FAINT)
    pdf.set_xy(tx, row_y)
    pdf.cell(tw_avail, 4, date_str, ln=True)
    pdf.set_x(tx)
    font(pdf, "B", 9.3)
    set_text(pdf, INK)
    title_w = tw_avail - (text_w(pdf, tag_text) + 8)
    pdf.cell(max(20, title_w), 5, truncate(pdf, title, max(20, title_w)), ln=False)
    badge(pdf, MARGIN + CONTENT_W - text_w(pdf, tag_text) - 6, pdf.get_y() - 0.3, tag_text, tag_color)
    pdf.ln(5.5)
    if subtitle:
        pdf.set_x(tx)
        font(pdf, "", 7.8)
        set_text(pdf, MUTED)
        pdf.multi_cell(tw_avail, 4, truncate(pdf, subtitle, tw_avail * 3))
    pdf.set_x(MARGIN)
    pdf.ln(2.5)


def mini_roadmap(pdf, phases):
    """
    Compact single-row visual roadmap for the Personal Growth page.
    phases: list of (label, sub, color, item_text)
    """
    n = len(phases)
    gap = 5
    w = (CONTENT_W - gap * (n - 1)) / n
    y = pdf.get_y()
    h = 34
    for i, (label, sub, color, item_text) in enumerate(phases):
        x = MARGIN + i * (w + gap)
        card_bg(pdf, x, y, w, h)
        set_fill(pdf, color)
        pdf.rect(x, y, w, 2.4, "F", round_corners=True, corner_radius=1.2)
        pdf.set_xy(x + 4, y + 5)
        font(pdf, "B", 9.5)
        set_text(pdf, color)
        pdf.cell(w - 8, 5, label, ln=True)
        pdf.set_x(x + 4)
        font(pdf, "", 7)
        set_text(pdf, FAINT)
        pdf.cell(w - 8, 4, sub, ln=True)
        pdf.set_x(x + 4)
        font(pdf, "", 7.8)
        set_text(pdf, MUTED)
        pdf.set_xy(x + 4, y + 15)
        pdf.multi_cell(w - 8, 4, truncate(pdf, item_text, (w - 8) * 4))
        if i < n - 1:
            set_draw(pdf, BORDER)
            pdf.set_line_width(0.3)
            ay = y + h / 2
            pdf.line(x + w + 0.5, ay, x + w + gap - 0.5, ay)
    pdf.set_xy(MARGIN, y + h + 5)
