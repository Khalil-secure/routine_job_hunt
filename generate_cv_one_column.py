"""
generate_cv_one_column.py — Single-column ReportLab CV renderer.
Entry point: build_cv(json_path, pdf_path)
Same JSON schema as generate_cv_last_version.py.
"""
import json
import re
import sys
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black, HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_HERE  = os.path.dirname(os.path.abspath(__file__))
_FONTS = os.path.join(_HERE, "fonts")
pdfmetrics.registerFont(TTFont("OpenSans",      os.path.join(_FONTS, "OpenSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("OpenSans-Bold", os.path.join(_FONTS, "OpenSans-Bold.ttf")))

SANS       = "OpenSans"
SANS_BOLD  = "OpenSans-Bold"
SERIF_BOLD = "Times-Bold"

PAGE_W, PAGE_H = A4      # 595.27 x 841.89 pt
MARGIN_L       = 36
MARGIN_R       = 36
BOTTOM_MARGIN  = 30
CONTENT_W      = PAGE_W - MARGIN_L - MARGIN_R   # ~523 pt
TEXT_X         = MARGIN_L + 12


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def wrap(c, text, max_w, font, size):
    words = text.split()
    if not words:
        return []
    lines, current = [], words[0]
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
    c.line(x, y_top,    x + arm, y_top)
    c.line(x, y_bottom, x + arm, y_bottom)


def section_header(c, text, y):
    c.setFont(SERIF_BOLD, 15)
    c.setFillColor(black)
    c.drawString(MARGIN_L, y, text)
    y -= 4
    c.setStrokeColor(HexColor("#CCCCCC"))
    c.setLineWidth(0.6)
    c.line(MARGIN_L, y, MARGIN_L + CONTENT_W, y)
    return y - 12


# ---------------------------------------------------------------------------
# Entry block
# ---------------------------------------------------------------------------

def draw_entry(c, y, title, sub1=None, sub2=None, body_items=None):
    max_w     = CONTENT_W - 14
    entry_top = y + 6

    c.setFont(SANS_BOLD, 8)
    c.setFillColor(black)
    for line in wrap(c, title.upper(), max_w, SANS_BOLD, 8):
        c.drawString(TEXT_X, y, line)
        y -= 10

    if sub1:
        c.setFont(SANS_BOLD, 9)
        c.drawString(TEXT_X, y, sub1)
        y -= 10

    if sub2:
        c.setFont(SANS_BOLD, 9)
        c.drawString(TEXT_X, y, sub2)
        y -= 11

    if body_items:
        c.setFont(SANS, 9)
        for item in body_items:
            lines = wrap(c, "• " + item, max_w, SANS, 9)
            for i, line in enumerate(lines):
                draw_x = TEXT_X if i == 0 else TEXT_X + 8
                c.drawString(draw_x, y, line)
                y -= 10
            y -= 1

    draw_bracket(c, MARGIN_L, entry_top, y + 4)
    y -= 10
    return y


def _estimate_entry_h(c, title, sub1, sub2, body_items):
    max_w = CONTENT_W - 14
    h = 6
    h += 10 * len(wrap(c, title.upper(), max_w, SANS_BOLD, 8))
    if sub1:  h += 10
    if sub2:  h += 11
    if body_items:
        for item in body_items:
            h += 10 * len(wrap(c, "• " + item, max_w, SANS, 9)) + 1
    h += 10
    return h


def _maybe_break(c, y, needed):
    if y - needed < BOTTOM_MARGIN:
        c.showPage()
        c.setFillColor(black)
        return PAGE_H - 30
    return y


# ---------------------------------------------------------------------------
# Inline sections (contacts, certs, skills, languages in single column)
# ---------------------------------------------------------------------------

def _draw_inline_row(c, y, label, value, max_w):
    label_str = label + " "
    lw = c.stringWidth(label_str, SANS_BOLD, 9)
    c.setFont(SANS_BOLD, 9)
    c.drawString(MARGIN_L, y, label_str)
    c.setFont(SANS, 9)
    val_lines = wrap(c, value, max_w - lw, SANS, 9)
    c.drawString(MARGIN_L + lw, y, val_lines[0] if val_lines else "")
    y -= 11
    for line in val_lines[1:]:
        c.drawString(MARGIN_L + lw, y, line)
        y -= 11
    return y


def draw_contacts_bar(c, data, y):
    en = data.get("_lang", "fr") == "en"
    identity = data["identity"]
    linkedin_raw = identity.get("linkedin", "")
    linkedin_display = re.sub(r"https?://(www\.)?", "", linkedin_raw).rstrip("/")

    contacts = [
        ("Address:" if en else "Adresse :",  identity["address"]),
        ("Phone:"   if en else "Tel :",       identity["phone"]),
        ("Email:",                             identity["email"]),
        ("LinkedIn:",                          linkedin_display),
    ]

    # Layout contacts in two columns for compactness
    col2_x = MARGIN_L + CONTENT_W // 2
    col_w  = CONTENT_W // 2 - 8
    pairs  = [(contacts[i], contacts[i + 1] if i + 1 < len(contacts) else None)
              for i in range(0, len(contacts), 2)]
    for left, right in pairs:
        # left label
        c.setFont(SANS_BOLD, 8)
        c.drawString(MARGIN_L, y, left[0])
        c.setFont(SANS, 8)
        val = wrap(c, left[1], col_w - c.stringWidth(left[0] + " ", SANS_BOLD, 8), SANS, 8)
        c.drawString(MARGIN_L + c.stringWidth(left[0] + " ", SANS_BOLD, 8), y, val[0] if val else "")
        # right label
        if right:
            c.setFont(SANS_BOLD, 8)
            c.drawString(col2_x, y, right[0])
            c.setFont(SANS, 8)
            val2 = wrap(c, right[1], col_w - c.stringWidth(right[0] + " ", SANS_BOLD, 8), SANS, 8)
            c.drawString(col2_x + c.stringWidth(right[0] + " ", SANS_BOLD, 8), y, val2[0] if val2 else "")
        y -= 13
    return y


def draw_skills_row(c, data, y):
    en    = data.get("_lang", "fr") == "en"
    skills = data.get("skills", [])
    certs  = data.get("certifications", [])
    langs  = data.get("languages", [])

    # Skills — 3 columns
    y = section_header(c, "Skills" if en else "Compétences", y)
    col_xs  = [MARGIN_L, MARGIN_L + CONTENT_W // 3, MARGIN_L + 2 * CONTENT_W // 3]
    cols    = [[], [], []]
    for i, sk in enumerate(skills):
        cols[i % 3].append(sk)
    max_rows = max((len(col) for col in cols), default=0)
    for row in range(max_rows):
        for ci, cx in enumerate(col_xs):
            if row < len(cols[ci]):
                sk = cols[ci][row]
                label_s = sk["label"] + " : "
                lw = c.stringWidth(label_s, SANS_BOLD, 8)
                c.setFont(SANS_BOLD, 8)
                c.drawString(cx, y, label_s)
                c.setFont(SANS, 8)
                c.drawString(cx + lw, y, sk["value"])
        y -= 12
    y -= 6

    # Certifications + Languages side by side
    half_w  = CONTENT_W // 2 - 8
    right_x = MARGIN_L + CONTENT_W // 2 + 8

    cert_hdr_y = y
    lang_hdr_y = y

    # — Certifications (left half) —
    c.setFont(SERIF_BOLD, 13)
    c.setFillColor(black)
    c.drawString(MARGIN_L, y, "Certifications")
    cy = y - 14
    for cert in certs:
        cert_line = f"• {cert['name']} ({cert['status']})"
        c.setFont(SANS_BOLD, 8)
        for line in wrap(c, cert_line, half_w, SANS_BOLD, 8):
            if cy >= BOTTOM_MARGIN:
                c.drawString(MARGIN_L, cy, line)
            cy -= 10
        c.setFont(SANS, 8)
        issuer_line = f"  {cert['issuer']}"
        if cy >= BOTTOM_MARGIN:
            c.drawString(MARGIN_L, cy, issuer_line)
        cy -= 11

    # — Languages (right half) —
    if langs:
        c.setFont(SERIF_BOLD, 13)
        c.setFillColor(black)
        c.drawString(right_x, y, "Languages" if en else "Langues")
        ly = y - 14
        for lang_entry in langs:
            label_s = lang_entry["label"] + " : "
            lw = c.stringWidth(label_s, SANS_BOLD, 9)
            c.setFont(SANS_BOLD, 9)
            if ly >= BOTTOM_MARGIN:
                c.drawString(right_x, ly, label_s)
            c.setFont(SANS, 9)
            if ly >= BOTTOM_MARGIN:
                c.drawString(right_x + lw, ly, lang_entry["value"])
            ly -= 13

    y = min(cy, ly if langs else cy) - 4
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

    # ── Header ───────────────────────────────────────────────────────────────
    y = PAGE_H - 30

    c.setFont(SANS_BOLD, 22)
    c.setFillColor(black)
    c.drawString(MARGIN_L, y, data["identity"]["full_name"])
    y -= 24

    display_title = data.get("_display_title") or data["identity"]["title"]
    c.setFont(SANS, 12)
    c.setFillColor(HexColor("#333333"))
    for line in wrap(c, display_title, CONTENT_W, SANS, 12):
        c.drawString(MARGIN_L, y, line)
        y -= 14
    c.setFillColor(black)
    y -= 2

    display_cert = data.get("_display_cert", "")
    if display_cert:
        c.setFont(SANS, 9)
        c.setFillColor(HexColor("#555555"))
        for line in wrap(c, display_cert, CONTENT_W, SANS, 9):
            c.drawString(MARGIN_L, y, line)
            y -= 11
        c.setFillColor(black)
        y -= 2

    meta_parts = [data["identity"].get("age", ""), data["identity"].get("permis", "")]
    meta_line  = "   ·   ".join(p for p in meta_parts if p)
    if meta_line:
        c.setFont(SANS, 9)
        c.setFillColor(HexColor("#888888"))
        c.drawString(MARGIN_L, y, meta_line)
        y -= 12

    c.setFillColor(black)
    summary = (data.get("profile") or {}).get("summary_fr", "")
    if summary:
        c.setFont(SANS, 9)
        c.setFillColor(HexColor("#444444"))
        for line in wrap(c, summary, CONTENT_W, SANS, 9):
            c.drawString(MARGIN_L, y, line)
            y -= 11
        c.setFillColor(black)
        y -= 3

    c.setStrokeColor(black)
    c.setLineWidth(1.2)
    c.line(MARGIN_L, y, MARGIN_L + CONTENT_W, y)
    y -= 10

    # Contacts bar
    y = draw_contacts_bar(c, data, y)
    y -= 4

    c.setStrokeColor(HexColor("#DDDDDD"))
    c.setLineWidth(0.6)
    c.line(MARGIN_L, y, MARGIN_L + CONTENT_W, y)
    y -= 12

    # ── Experience ───────────────────────────────────────────────────────────
    y = section_header(c, "Experience" if en else "Expériences", y)
    for exp in data["experience"]:
        needed = _estimate_entry_h(c, exp["title"], exp["period"],
                                   f"{exp['company']} - {exp['location']}",
                                   exp["bullets"])
        y = _maybe_break(c, y, needed)
        y = draw_entry(c, y,
                       title=exp["title"],
                       sub1=exp["period"],
                       sub2=f"{exp['company']} - {exp['location']}",
                       body_items=exp["bullets"])

    # ── Education ────────────────────────────────────────────────────────────
    y = _maybe_break(c, y, 60)
    y = section_header(c, "Education" if en else "Études - Diplômes", y)
    for edu in data["education"]:
        needed = _estimate_entry_h(c, edu["degree"], edu["year"],
                                   f"{edu['school']} - {edu['location']}",
                                   [edu["details"]])
        y = _maybe_break(c, y, needed)
        y = draw_entry(c, y,
                       title=edu["degree"],
                       sub1=edu["year"],
                       sub2=f"{edu['school']} - {edu['location']}",
                       body_items=[edu["details"]])

    # ── Projects ─────────────────────────────────────────────────────────────
    y = _maybe_break(c, y, 60)
    y = section_header(c, "Personal Projects" if en else "Projets académiques / personnels", y)
    for proj in data["projects"]:
        proj_title = f"Project {proj['name']}" if en else f"Projet {proj['name']}"
        needed = _estimate_entry_h(c, proj_title, None, None, [proj["description"]])
        y = _maybe_break(c, y, needed)
        y = draw_entry(c, y, title=proj_title, body_items=[proj["description"]])

    # ── Skills / Certs / Languages ───────────────────────────────────────────
    y = _maybe_break(c, y, 80)
    y -= 4
    y = draw_skills_row(c, data, y)

    c.save()
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    json_in  = sys.argv[1] if len(sys.argv) > 1 else "cv_main.json"
    pdf_out  = sys.argv[2] if len(sys.argv) > 2 else "soc_cv_one_col.pdf"
    build_cv(json_in, pdf_out)
