# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Automated French job-hunting pipeline: a Chrome extension extracts job descriptions from French job boards, POSTs the payload to a local FastAPI backend, which calls Groq (`meta-llama/llama-4-scout-17b-16e-instruct`) to generate a targeted CV PDF and cover letter. Applications are tracked in `suivi.json` and optionally synced to Google Sheets.

## Commands

```bash
# Start the backend API
uvicorn backend:app --port 8000 --reload

# Run the standalone ATS scoring loop (no server needed)
python ats_optimizer.py

# Generate a PDF from a JSON CV file directly
python generate_cv_last_version.py <input.json> <output.pdf>

# Set up Google Sheets integration (interactive)
python setup_sheets.py

# Install dependencies
pip install -r requirements.txt
```

**Test the running backend:**
```powershell
$BaseUrl = "http://localhost:8000"
Invoke-RestMethod "$BaseUrl/health"    # → { status: "ok" }
# Dashboard lives at http://localhost:8000
```

**Quick Groq sanity check (no server needed):**
```bash
python test_groq.py   # NOTE: test_groq.py is stale — it references PROMPT_TEMPLATE which no longer exists in backend.py
```

## Architecture

### Data flow

```
Chrome Extension (content.js + popup.js)
    ↓  POST {meta, job, for_ai}  →  http://localhost:8000/generate-cv
                                 →  http://localhost:8000/generate-letter
backend.py  (FastAPI, port 8000)
    ↓  reads cv_master_profile.json + cv_main.json
    ↓  _patch_cv_soc() → Groq API → patched JSON
    ↓  render_pdf() → generate_cv_last_version.py → PDF (CV_jobs/)
    ↓  _render_letter_pdf() → ReportLab → PDF (lettres/)
    ↓  suivi.json (local) + Google Sheets (optional)
```

### Key files

| File | Role |
|---|---|
| `backend.py` | FastAPI app — all API routes, Groq orchestration, dashboard HTML |
| `generate_cv_last_version.py` | ReportLab PDF renderer — `build_cv(json_path, pdf_path)` |
| `ats_optimizer.py` | Standalone iterative ATS scoring loop (up to 6 rounds, target ≥ 90%) |
| `sheets.py` | Google Sheets sync — silent no-op if `google_credentials.json` absent |
| `cv_master_profile.json` | Full candidate profile: all projects, experience, keywords bank |
| `cv_main.json` | Base CV template — frozen base that `_patch_cv_soc()` mutates |
| `suivi.json` | Application tracking log (newest-first, auto-updated on every CV generation) |
| `cv-extractor-v5/cv-extractor/` | Chrome extension (Manifest V3) |

### CV generation logic (`_patch_cv_soc`)

The backend does **not** generate a full CV from scratch. It takes `cv_main.json` as a frozen base template and patches exactly 4 things via a single Groq call:
1. `identity.title` — job title (2–6 words, rejected if it looks like a sentence)
2. `projects` — exactly 5, selected from master pool scored by keyword overlap; descriptions ATS-enriched using X-Y method (190–230 chars)
3. `skills` — flat list `[{label, value}]`, max 31 entries, reordered/relabelled from the existing soc-cv skill list; hard-cap 28 chars on `value`
4. `keyword_bullet` — one bullet injected into the best-matching existing experience (`exp_index` field chooses which)

Everything else (experience body, education, certifications) stays as-is from `cv_main.json`. The `soft_skills` key is stripped from the output. Groq is called with `response_format={"type": "json_object"}` and up to 3 retries with increasing temperature.

**Note:** `cv_main.json` skills are a flat array `[{label, value}]`, not the categorized dict structure in `cv_master_profile.json`. These are two distinct schemas.

### Bilingual support

`POST /generate-cv` accepts `meta.lang` (`"fr"` default or `"en"`). This is forwarded to `_patch_cv_soc`, which changes the Groq instruction language and the skill value vocabulary (`expert/avancé/confirmé` vs `expert/advanced/proficient`). The `_lang` field is written into the CV JSON and read by `generate_cv_last_version.py` to switch section headers and contact labels.

### `_filter_profile` (used for cover letter generation)

Takes `cv_master_profile.json` and the job description, keyword-scores every experience/project/skill, and returns a trimmed version sent to Groq for letter generation. Experiences are sorted by relevance (all kept, missions truncated to 200 chars); only top-5 projects are kept; skill categories with zero matching items are still included but capped at their top-2 items.

### Chrome extension extraction strategy (`content.js`)

Four-layer cascade, in order:
1. **JSON-LD** — structured `JobPosting` data (works on non-auth pages)
2. **Anchor selectors** — CSS selectors for LinkedIn, Glassdoor, WTTJ, Indeed, Hellowork, Pôle Emploi, APEC
3. **MutationObserver** — waits up to 12 s for SPA render, then retries layers 1–2
4. **Nuclear fallback** — largest clean text block in the DOM

### API routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard (self-contained HTML) |
| `GET` | `/health` | Health check |
| `GET` | `/suivi` | Return all tracking entries |
| `PATCH` | `/suivi/{id}` | Update status/notes, syncs to Sheets |
| `POST` | `/generate-cv` | Generate targeted CV PDF |
| `POST` | `/generate-letter` | Generate cover letter PDF |

### Debug files (auto-saved, not committed)

- `_last_joboffer.json` — last raw job payload received by `/generate-cv`
- `_last_generated_cv.json` — last CV JSON produced by `_patch_cv_soc` before PDF render

### Environment variables (`.env`)

```
Groq_API_text_analysis=<groq_api_key>
GOOGLE_SHEET_ID=<spreadsheet_id>          # optional
```

Google Sheets additionally requires `google_credentials.json` (service account key) in the project root.

### PDF layout (`generate_cv_last_version.py`)

Two-column ReportLab layout on A4:
- **Left column** (`MAIN_X=30`, width 368 pt): name, title, experience, education, projects — each entry wrapped in a `[` bracket drawn by `draw_bracket()`
- **Right column** (`SIDEBAR_X=420`): contacts, certifications, skills, languages
- Fonts: OpenSans-Regular/Bold from `fonts/`; Times-Bold for section headers

`build_cv(json_path, pdf_path)` is the single entry point called by `backend.py` as `render_pdf()`. Page breaks are estimated via `_estimate_entry_h()` before drawing.

Cover letter PDFs are rendered inline in `backend.py` via `_render_letter_pdf()` (ReportLab, A4, word-wrapped paragraphs, no separate module).

### Application tracking

`suivi.json` stores entries newest-first. Each entry has a UUID `id` used to match rows in Google Sheets for status updates. Valid statuses: `cv_generated → applied → interview → offer → rejected → ghosted`. The dashboard at `GET /` serves a self-contained HTML page that reads from `GET /suivi` and patches via `PATCH /suivi/{id}`.

### Output directories

- `CV_jobs/` — generated PDF CVs (auto-created)
- `lettres/` — generated cover letter PDFs (auto-created)
- `ats_runs/` — `ats_optimizer.py` iteration snapshots (auto-created)
