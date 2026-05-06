import json
import re
import sys
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black, white, HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_HERE  = os.path.dirname(os.path.abspath(__file__))
_FONTS = os.path.join(_HERE, "fonts")
pdfmetrics.registerFont(TTFont("OpenSans",      os.path.join(_FONTS, "OpenSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("OpenSans-Bold", os.path.join(_FONTS, "OpenSans-Bold.ttf")))

SANS       = "OpenSans"
SANS_BOLD  = "OpenSans-Bold"
SERIF_BOLD = "Times-Bold"

PAGE_W, PAGE_H = A4          # 595 x 842 pt

MARGIN_L   = 50
MARGIN_R   = 50
MARGIN_BOT = 36
CONTENT_W  = PAGE_W - MARGIN_L - MARGIN_R   # ~495 pt

ACCENT     = HexColor("#1a73e8")   # Google blue
LIGHT_GRAY = HexColor("#f1f3f4")
MID_GRAY   = HexColor("#5f6368")
DARK       = HexColor("#202124")


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def wrap(c, text, max_w, font, size):
    words = text.split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for w in words[1:]:
        cand = current + " " + w
        if c.stringWidth(cand, font, size) <= max_w:
            current = cand
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def new_page(c):
    c.showPage()
    return PAGE_H - 36


def maybe_break(c, y, needed):
    if y - needed < MARGIN_BOT:
        y = new_page(c)
    return y


# ---------------------------------------------------------------------------
# Header block  (name + contact strip)
# ---------------------------------------------------------------------------

def draw_header(c, data):
    en = data.get("_lang", "fr") == "en"
    identity = data["identity"]

    # ── Name bar ────────────────────────────────────────────────────────────
    y = PAGE_H - 30
    c.setFillColor(DARK)
    c.setFont(SANS_BOLD, 26)
    c.drawString(MARGIN_L, y, identity["full_name"])
    y -= 22

    # Tagline / title
    tagline = data.get("_tagline", "")
    if tagline:
        c.setFont(SANS, 11)
        c.setFillColor(ACCENT)
        c.drawString(MARGIN_L, y, tagline)
        y -= 14

    # Age + permis  (small gray line)
    meta = "  •  ".join(filter(None, [identity.get("age"), identity.get("permis")]))
    if meta:
        c.setFont(SANS, 9)
        c.setFillColor(MID_GRAY)
        c.drawString(MARGIN_L, y, meta)
        y -= 12

    # Summary
    summary = (data.get("profile") or {}).get("summary_fr", "")
    if summary:
        c.setFont(SANS, 9)
        c.setFillColor(DARK)
        for line in wrap(c, summary, CONTENT_W, SANS, 9):
            c.drawString(MARGIN_L, y, line)
            y -= 11
        y -= 4

    # ── Contact strip  ───────────────────────────────────────────────────────
    y -= 4
    strip_h = 22
    c.setFillColor(LIGHT_GRAY)
    c.rect(MARGIN_L - 8, y - strip_h + 8, CONTENT_W + 16, strip_h, fill=1, stroke=0)

    linkedin_raw = identity.get("linkedin", "")
    linkedin_display = re.sub(r"https?://(www\.)?", "", linkedin_raw).rstrip("/")
    contacts = [identity.get("address", ""), identity.get("phone", ""),
                identity.get("email", ""), linkedin_display]
    contacts = [c_ for c_ in contacts if c_]

    c.setFont(SANS, 8)
    c.setFillColor(MID_GRAY)
    sep_w = c.stringWidth("  |  ", SANS, 8)
    x = MARGIN_L - 2
    cy = y - 10
    for i, item in enumerate(contacts):
        c.drawString(x, cy, item)
        x += c.stringWidth(item, SANS, 8)
        if i < len(contacts) - 1:
            c.drawString(x, cy, "  |  ")
            x += sep_w

    y -= strip_h + 6

    # ── Thick accent rule ────────────────────────────────────────────────────
    c.setStrokeColor(ACCENT)
    c.setLineWidth(2.5)
    c.line(MARGIN_L, y, MARGIN_L + CONTENT_W, y)
    y -= 12

    return y


# ---------------------------------------------------------------------------
# Section heading
# ---------------------------------------------------------------------------

def section_heading(c, text, y):
    y = maybe_break(c, y, 28)
    c.setFont(SANS_BOLD, 11)
    c.setFillColor(ACCENT)
    c.drawString(MARGIN_L, y, text.upper())
    y -= 4
    c.setStrokeColor(HexColor("#dadce0"))
    c.setLineWidth(0.8)
    c.line(MARGIN_L, y, MARGIN_L + CONTENT_W, y)
    y -= 10
    return y


# ---------------------------------------------------------------------------
# Entry  (experience / education / project)
# ---------------------------------------------------------------------------

def estimate_entry_h(c, title, right_text, sub1, sub2, bullets):
    h = 0
    title_lines = len(wrap(c, title, CONTENT_W * 0.65, SANS_BOLD, 10))
    h += title_lines * 12
    if sub1:
        h += 11
    if sub2:
        h += 10
    if bullets:
        for b in bullets:
            h += len(wrap(c, b, CONTENT_W - 14, SANS, 9)) * 10 + 2
    h += 8   # bottom gap
    return h


def draw_entry(c, y, title, right_text=None, sub1=None, sub2=None, bullets=None):
    """
    title      – bold role/degree name  (left)
    right_text – period / date          (right-aligned, gray)
    sub1       – company or school      (italic-weight bold)
    sub2       – location               (gray)
    bullets    – list[str]
    """
    # Title row
    c.setFont(SANS_BOLD, 10)
    c.setFillColor(DARK)
    title_max_w = CONTENT_W - (c.stringWidth(right_text or "", SANS, 9) + 6)
    for line in wrap(c, title, title_max_w, SANS_BOLD, 10):
        c.drawString(MARGIN_L, y, line)
        if right_text:
            c.setFont(SANS, 9)
            c.setFillColor(MID_GRAY)
            tw = c.stringWidth(right_text, SANS, 9)
            c.drawString(MARGIN_L + CONTENT_W - tw, y, right_text)
            right_text = None   # only on first line
            c.setFont(SANS_BOLD, 10)
            c.setFillColor(DARK)
        y -= 12

    if sub1:
        c.setFont(SANS_BOLD, 9)
        c.setFillColor(HexColor("#3c4043"))
        c.drawString(MARGIN_L + 2, y, sub1)
        y -= 11

    if sub2:
        c.setFont(SANS, 9)
        c.setFillColor(MID_GRAY)
        c.drawString(MARGIN_L + 2, y, sub2)
        y -= 10

    if bullets:
        c.setFont(SANS, 9)
        c.setFillColor(DARK)
        for b in bullets:
            lines = wrap(c, b, CONTENT_W - 16, SANS, 9)
            for i, line in enumerate(lines):
                prefix = "•  " if i == 0 else "    "
                c.drawString(MARGIN_L + 8, y, prefix + line)
                y -= 10
            y -= 2

    y -= 8
    return y


# ---------------------------------------------------------------------------
# Sidebar-style skills / certs / languages  (now inline, two-column grid)
# ---------------------------------------------------------------------------

def draw_two_col_section(c, y, items_left, items_right):
    """Draw two lists side by side (skills / languages / hobbies)."""
    col_w = CONTENT_W // 2 - 10
    y_start = y
    y_l = y_start
    for label, value in items_left:
        c.setFont(SANS_BOLD, 9)
        c.setFillColor(DARK)
        lw = c.stringWidth(label + " : ", SANS_BOLD, 9)
        c.drawString(MARGIN_L, y_l, label + " : ")
        c.setFont(SANS, 9)
        c.setFillColor(MID_GRAY)
        c.drawString(MARGIN_L + lw, y_l, value)
        y_l -= 12

    y_r = y_start
    for label, value in items_right:
        c.setFont(SANS_BOLD, 9)
        c.setFillColor(DARK)
        lw = c.stringWidth(label + " : ", SANS_BOLD, 9)
        c.drawString(MARGIN_L + col_w + 20, y_r, label + " : ")
        c.setFont(SANS, 9)
        c.setFillColor(MID_GRAY)
        c.drawString(MARGIN_L + col_w + 20 + lw, y_r, value)
        y_r -= 12

    return min(y_l, y_r) - 6


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_cv(json_path="cv_main.json", output_path="soc_cv_output.pdf"):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle("CV - " + data["identity"]["full_name"])

    en = data.get("_lang", "fr") == "en"

    # Header
    y = draw_header(c, data)

    # ── Experience ───────────────────────────────────────────────────────────
    y = section_heading(c, "Experience" if en else "Expériences", y)
    for exp in data["experience"]:
        needed = estimate_entry_h(c, exp["title"], exp["period"],
                                  exp["company"],
                                  exp["location"], exp["bullets"])
        y = maybe_break(c, y, needed)
        y = draw_entry(c, y,
                       title=exp["title"],
                       right_text=exp["period"],
                       sub1=exp["company"],
                       sub2=exp["location"],
                       bullets=exp["bullets"])

    # ── Education ────────────────────────────────────────────────────────────
    y = maybe_break(c, y, 40)
    y = section_heading(c, "Education" if en else "Études - Diplômes", y)
    for edu in data["education"]:
        needed = estimate_entry_h(c, edu["degree"], edu["year"],
                                  edu["school"], edu["location"],
                                  [edu["details"]])
        y = maybe_break(c, y, needed)
        y = draw_entry(c, y,
                       title=edu["degree"],
                       right_text=edu["year"],
                       sub1=edu["school"],
                       sub2=edu["location"],
                       bullets=[edu["details"]])

    # ── Projects ─────────────────────────────────────────────────────────────
    y = maybe_break(c, y, 40)
    y = section_heading(c, "Personal Projects" if en else "Projets académiques / personnels", y)
    for proj in data["projects"]:
        proj_title = f"Project {proj['name']}" if en else f"Projet {proj['name']}"
        needed = estimate_entry_h(c, proj_title, None, None, None,
                                  [proj["description"]])
        y = maybe_break(c, y, needed)
        y = draw_entry(c, y,
                       title=proj_title,
                       bullets=[proj["description"]])

    # ── Skills ───────────────────────────────────────────────────────────────
    if data.get("skills"):
        y = maybe_break(c, y, 40)
        y = section_heading(c, "Skills" if en else "Compétences", y)
        skills = data["skills"]
        mid = (len(skills) + 1) // 2
        left  = [(s["label"], s["value"]) for s in skills[:mid]]
        right = [(s["label"], s["value"]) for s in skills[mid:]]
        y = draw_two_col_section(c, y, left, right)

    # ── Certifications ───────────────────────────────────────────────────────
    if data.get("certifications"):
        y = maybe_break(c, y, 40)
        y = section_heading(c, "Certifications", y)
        for cert in data["certifications"]:
            cert_title = f"{cert['name']} ({cert['status']})"
            needed = estimate_entry_h(c, cert_title, None, cert["issuer"], None, None)
            y = maybe_break(c, y, needed)
            y = draw_entry(c, y,
                           title=cert_title,
                           sub1=cert["issuer"])

    # ── Languages ────────────────────────────────────────────────────────────
    if data.get("languages"):
        y = maybe_break(c, y, 40)
        y = section_heading(c, "Languages" if en else "Langues", y)
        langs = data["languages"]
        mid = (len(langs) + 1) // 2
        left  = [(l["label"], l["value"]) for l in langs[:mid]]
        right = [(l["label"], l["value"]) for l in langs[mid:]]
        y = draw_two_col_section(c, y, left, right)

    # ── Hobbies ──────────────────────────────────────────────────────────────
    if data.get("hobbies"):
        y = maybe_break(c, y, 40)
        y = section_heading(c, "Interests" if en else "Centres d'intérêt", y)
        c.setFont(SANS, 9)
        c.setFillColor(DARK)
        hobbies_line = "  •  ".join(data["hobbies"])
        for line in wrap(c, hobbies_line, CONTENT_W, SANS, 9):
            c.drawString(MARGIN_L, y, line)
            y -= 11

    c.save()
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    json_in  = sys.argv[1] if len(sys.argv) > 1 else "khalil_soc_cv.json"
    pdf_out  = sys.argv[2] if len(sys.argv) > 2 else "soc_cv_output.pdf"
    build_cv(json_in, pdf_out)