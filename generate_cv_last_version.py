import json
import re
import sys
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black, HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Register Open Sans — TTF files sit next to this script
_HERE  = os.path.dirname(os.path.abspath(__file__))
_FONTS = os.path.join(_HERE, "fonts")
pdfmetrics.registerFont(TTFont("OpenSans",      os.path.join(_FONTS, "OpenSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("OpenSans-Bold", os.path.join(_FONTS, "OpenSans-Bold.ttf")))

SANS       = "OpenSans"
SANS_BOLD  = "OpenSans-Bold"
SERIF_BOLD = "Times-Bold"

PAGE_W, PAGE_H = A4  # 595.27 x 841.89 pt

MAIN_X         = 30
MAIN_W         = 368          # page 1 main column width
PAGE2_MAIN_W   = int(PAGE_W - 60)  # ~535 pt on page 2+ (no sidebar)
SIDEBAR_LINE_X = 410
SIDEBAR_X      = 420
BOTTOM_MARGIN  = 30


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def wrap(c, text, max_w, font, size):
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if c.stringWidth(candidate, font, size) <= max_w:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_bracket(c, x, y_top, y_bottom, arm=5):
    c.setStrokeColor(black)
    c.setLineWidth(0.9)
    c.line(x, y_top, x, y_bottom)
    c.line(x, y_top, x + arm, y_top)
    c.line(x, y_bottom, x + arm, y_bottom)


def sidebar_chrome(c, start_y=None):
    line_top = start_y if start_y is not None else PAGE_H - BOTTOM_MARGIN
    c.setStrokeColor(black)
    c.setLineWidth(1.5)
    c.line(SIDEBAR_LINE_X, line_top, SIDEBAR_LINE_X, BOTTOM_MARGIN)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def draw_sidebar(c, data, start_y=None):
    max_side_w = PAGE_W - SIDEBAR_X - 8
    y = start_y if start_y is not None else PAGE_H - 30

    en = data.get("_lang", "fr") == "en"

    def safe_draw_string(x, y_, text):
        if y_ >= BOTTOM_MARGIN:
            c.drawString(x, y_, text)

    linkedin_raw = data["identity"].get("linkedin", "")
    linkedin_display = re.sub(r"https?://(www\.)?", "", linkedin_raw).rstrip("/")

    contacts = [
        ("Address:" if en else "Adresse :", data["identity"]["address"]),
        ("Phone:"   if en else "Téléphone :", data["identity"]["phone"]),
        ("Email:",                             data["identity"]["email"]),
        ("LinkedIn:",                          linkedin_display),
    ]
    for label, value in contacts:
        if y < BOTTOM_MARGIN: break
        c.setFont(SANS_BOLD, 9)
        c.setFillColor(black)
        safe_draw_string(SIDEBAR_X, y, label)
        y -= 11
        c.setFont(SANS, 9)
        for line in wrap(c, value, max_side_w, SANS, 9):
            safe_draw_string(SIDEBAR_X, y, line)
            y -= 10
        y -= 5

    y -= 3
    if y >= BOTTOM_MARGIN:
        c.setFont(SERIF_BOLD, 13)
        safe_draw_string(SIDEBAR_X, y, "Certifications")
        y -= 14

    for cert in data["certifications"]:
        if y < BOTTOM_MARGIN: break
        cert_line = f"{cert['name']} ({cert['status']})"
        c.setFont(SANS_BOLD, 8)
        for line in wrap(c, cert_line, max_side_w, SANS_BOLD, 8):
            safe_draw_string(SIDEBAR_X, y, line)
            y -= 10
        c.setFont(SANS, 8)
        safe_draw_string(SIDEBAR_X, y, cert["issuer"])
        y -= 12

    y -= 4
    if y >= BOTTOM_MARGIN:
        c.setFont(SERIF_BOLD, 13)
        safe_draw_string(SIDEBAR_X, y, "Skills" if en else "Compétences")
        y -= 14

    for skill in data["skills"]:
        if y < BOTTOM_MARGIN: break
        label_str = skill["label"] + " : "
        value_str = skill["value"]
        c.setFont(SANS_BOLD, 8)
        lw = c.stringWidth(label_str, SANS_BOLD, 8)
        safe_draw_string(SIDEBAR_X, y, label_str)
        c.setFont(SANS, 8)
        safe_draw_string(SIDEBAR_X + lw, y, value_str)
        y -= 11

    if data.get("languages"):
        y -= 4
        if y >= BOTTOM_MARGIN:
            c.setFont(SERIF_BOLD, 13)
            safe_draw_string(SIDEBAR_X, y, "Languages" if en else "Langues")
            y -= 14
        for lang_entry in data["languages"]:
            if y < BOTTOM_MARGIN: break
            label_str = lang_entry["label"] + " : "
            value_str = lang_entry["value"]
            c.setFont(SANS_BOLD, 8)
            lw = c.stringWidth(label_str, SANS_BOLD, 8)
            safe_draw_string(SIDEBAR_X, y, label_str)
            c.setFont(SANS, 8)
            safe_draw_string(SIDEBAR_X + lw, y, value_str)
            y -= 11

    if data.get("hobbies"):
        y -= 4
        if y >= BOTTOM_MARGIN:
            c.setFont(SERIF_BOLD, 13)
            safe_draw_string(SIDEBAR_X, y, "Interests" if en else "Centres d'intérêt")
            y -= 14
        c.setFont(SANS, 8)
        for hobby in data["hobbies"]:
            if y < BOTTOM_MARGIN: break
            for line in wrap(c, f"• {hobby}", max_side_w, SANS, 8):
                safe_draw_string(SIDEBAR_X, y, line)
                y -= 10
            y -= 2


# ---------------------------------------------------------------------------
# Entry block
# ---------------------------------------------------------------------------

def draw_entry(c, y, title, sub1=None, sub2=None, body_items=None, main_w=None, state=None):
    effective_w = main_w if main_w is not None else MAIN_W
    max_w       = effective_w - 14
    text_x      = MAIN_X + 12
    entry_top   = y + 6

    c.setFont(SANS_BOLD, 8)
    c.setFillColor(black)
    for line in wrap(c, title.upper(), max_w, SANS_BOLD, 8):
        c.drawString(text_x, y, line)
        y -= 10

    if sub1:
        c.setFont(SANS_BOLD, 9)
        c.drawString(text_x, y, sub1)
        y -= 10

    if sub2:
        c.setFont(SANS_BOLD, 9)
        c.drawString(text_x, y, sub2)
        y -= 11

    if body_items:
        c.setFont(SANS, 9)
        for item in body_items:
            lines = wrap(c, "• " + item, max_w, SANS, 9)
            for i, line in enumerate(lines):
                draw_x = text_x if i == 0 else text_x + 8
                c.drawString(draw_x, y, line)
                y -= 10
            y -= 1

    draw_bracket(c, MAIN_X, entry_top, y + 4)
    y -= 10
    return y


def section_header(c, text, y):
    c.setFont(SERIF_BOLD, 16)
    c.setFillColor(black)
    c.drawString(MAIN_X, y, text)
    return y - 16


# ---------------------------------------------------------------------------
# Page management
# ---------------------------------------------------------------------------

def _estimate_entry_h(c, title, sub1, sub2, body_items, main_w=None):
    effective_w = main_w if main_w is not None else MAIN_W
    max_w = effective_w - 14
    h = 6
    h += 10 * len(wrap(c, title.upper(), max_w, SANS_BOLD, 8))
    if sub1:
        h += 10
    if sub2:
        h += 11
    if body_items:
        for item in body_items:
            h += 10 * len(wrap(c, "• " + item, max_w, SANS, 9)) + 1
    h += 10
    return h


def _new_page(c, data):
    """Flush current page, start a fresh continuation page (no sidebar on p2+)."""
    c.showPage()
    c.setFillColor(black)
    return PAGE_H - 30


def _maybe_break(c, y, data, needed, state):
    """Move the entire block to the next page if it would touch the bottom margin."""
    if y - needed < BOTTOM_MARGIN:
        y = _new_page(c, data)
        state["on_page_one"] = False
        state["main_w"] = PAGE2_MAIN_W
    return y


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_cv(json_path="cv_main.json", output_path="soc_cv_output.pdf"):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle("CV - " + data["identity"]["full_name"])

    en = data.get("_lang", "fr") == "en"

    # ── Header (main column) ─────────────────────────────────────────────────
    y = PAGE_H - 30
    c.setFillColor(black)

    c.setFont(SANS_BOLD, 20)
    c.drawString(MAIN_X, y, data["identity"]["full_name"])
    y -= 22

    display_title = data.get("_display_title") or data["identity"]["title"]
    c.setFont(SANS, 11)
    c.setFillColor(HexColor("#333333"))
    for line in wrap(c, display_title, MAIN_W - 4, SANS, 11):
        c.drawString(MAIN_X, y, line)
        y -= 13
    c.setFillColor(black)
    y -= 2

    display_cert = data.get("_display_cert", "")
    if display_cert:
        c.setFont(SANS, 9)
        c.setFillColor(HexColor("#555555"))
        for line in wrap(c, display_cert, MAIN_W - 4, SANS, 9):
            c.drawString(MAIN_X, y, line)
            y -= 11
        c.setFillColor(black)
        y -= 2

    c.setFont(SANS, 9)
    c.setFillColor(HexColor("#666666"))
    c.drawString(MAIN_X, y, data["identity"]["age"])
    y -= 11
    c.setFillColor(black)

    c.setFont(SANS, 10)
    c.drawString(MAIN_X, y, data["identity"]["permis"])
    y -= 13

    summary = (data.get("profile") or {}).get("summary_fr", "")
    if summary:
        c.setFont(SANS, 9)
        c.setFillColor(HexColor("#444444"))
        for line in wrap(c, summary, MAIN_W - 4, SANS, 9):
            c.drawString(MAIN_X, y, line)
            y -= 11
        c.setFillColor(black)
        y -= 4

    c.setStrokeColor(black)
    c.setLineWidth(0.8)
    c.line(MAIN_X, y, MAIN_X + MAIN_W, y)
    y -= 16

    # Sidebar line and content both start aligned with the section content
    sidebar_start_y = y
    sidebar_chrome(c, start_y=sidebar_start_y)
    draw_sidebar(c, data, start_y=sidebar_start_y)

    # ── State for dynamic column width across pages ───────────────────────────
    state = {"main_w": MAIN_W, "on_page_one": True}

    # ── Sections ─────────────────────────────────────────────────────────────
    y = section_header(c, "Experience" if en else "Expériences", y)
    for exp in data["experience"]:
        needed = _estimate_entry_h(c, exp["title"], exp["period"],
                                   f"{exp['company']} - {exp['location']}",
                                   exp["bullets"], main_w=state["main_w"])
        y = _maybe_break(c, y, data, needed, state)
        y = draw_entry(c, y,
                       title=exp["title"],
                       sub1=exp["period"],
                       sub2=f"{exp['company']} - {exp['location']}",
                       body_items=exp["bullets"],
                       main_w=state["main_w"],
                       state=state)

    y = _maybe_break(c, y, data, 60, state)
    y = section_header(c, "Education" if en else "Études - Diplômes", y)
    for edu in data["education"]:
        needed = _estimate_entry_h(c, edu["degree"], edu["year"],
                                   f"{edu['school']} - {edu['location']}",
                                   [edu["details"]], main_w=state["main_w"])
        y = _maybe_break(c, y, data, needed, state)
        y = draw_entry(c, y,
                       title=edu["degree"],
                       sub1=edu["year"],
                       sub2=f"{edu['school']} - {edu['location']}",
                       body_items=[edu["details"]],
                       main_w=state["main_w"],
                       state=state)

    y = _maybe_break(c, y, data, 60, state)
    y = section_header(c, "Personal Projects" if en else "Projets académiques / personnels", y)
    for proj in data["projects"]:
        proj_title = f"Project {proj['name']}" if en else f"Projet {proj['name']}"
        needed = _estimate_entry_h(c, proj_title, None, None,
                                   [proj["description"]], main_w=state["main_w"])
        y = _maybe_break(c, y, data, needed, state)
        y = draw_entry(c, y,
                       title=proj_title,
                       body_items=[proj["description"]],
                       main_w=state["main_w"],
                       state=state)

    c.save()
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    json_in = sys.argv[1] if len(sys.argv) > 1 else "khalil_soc_cv.json"
    pdf_out = sys.argv[2] if len(sys.argv) > 2 else "soc_cv_output.pdf"
    build_cv(json_in, pdf_out)
