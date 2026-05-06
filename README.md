# AI CV Generator — Job Hunt Automation

Automated job-hunting pipeline. A Chrome extension extracts job descriptions from any job board, sends them to a local FastAPI backend, which calls Groq (Llama 4) to generate a targeted CV PDF and cover letter — tailored to the exact offer in ~15 seconds.

Supports French and English, two-column and one-column PDF layouts, and tracks every application in a local dashboard.

---

## How it works

```
Job board page
    ↓  Chrome extension extracts job description
    ↓  POST to http://localhost:8000
Backend (FastAPI)
    ↓  Reads your master profile JSON
    ↓  Calls Groq → patches CV JSON (title, projects, skills, keywords)
    ↓  Renders PDF via ReportLab
    ↓  Saves to CV_jobs/ and logs to suivi.json
```

---

## Onboarding — Setting up your profile

You need four files before the backend can generate anything:

| File | Purpose |
|---|---|
| `cv_main.json` | Your French base CV — the frozen template the AI patches per job offer |
| `cv_main_en.json` | Same CV in English — used when you select English in the extension |
| `cv_master_profile.json` | Full profile pool — all projects, experience, keywords; used for cover letters and project selection |
| `user_config.json` | Prompt config — your owned professional titles and cover letter tone |

There are two ways to create these files:

---

### Method A — Claude skill (recommended)

The skill at `onboarding/setup-cv-generator.md` guides Claude through a structured interview and generates all four files for you.

**Steps:**

1. Open [claude.ai/code](https://claude.ai/code) or Claude Code in your terminal
2. Navigate to this project folder:
   ```
   cd path/to/routine_job_hunt
   ```
3. Load the skill by running the slash command:
   ```
   /setup-cv-generator
   ```
   If the skill isn't registered, open `onboarding/setup-cv-generator.md` and paste the content into your conversation, or tell Claude:
   > "Follow the instructions in onboarding/setup-cv-generator.md and set up my CV generator profile"

4. Claude will interview you in structured blocks:
   - Personal and contact information
   - Professional identity and target roles
   - Work experience (each job, bullets, alternative titles for variants)
   - Education
   - Certifications
   - Technical skills with proficiency levels
   - Personal and academic projects
   - Languages
   - Cover letter tone and preferences
   - Owned professional titles (what roles you can legitimately claim)
   - Profile summary examples calibrated to your target role types

5. Claude generates all four files — copy each one into the project root

**Claude will ask for everything it needs. It will not invent or assume anything missing.**

---

### Method B — Manual (fill out the templates)

If you prefer to write the files yourself, use the schemas below. Place all four files in the project root (same folder as `backend.py`) when done.

#### `cv_main.json` — French base CV template

Only 4 things get patched per job application: title, projects, skills, and one keyword bullet in the best-matching experience. Everything else (experience bullets, education, certifications) stays exactly as you write it.

```json
{
  "identity": {
    "full_name": "Your Name",
    "title": "Your current job title (2–6 words)",
    "age": "24 ans",
    "permis": "Permis B",
    "address": "75000 Paris",
    "phone": "0600000000",
    "email": "you@example.com",
    "linkedin": "https://www.linkedin.com/in/your-profile",
    "github": "https://github.com/your-handle"
  },
  "experience": [
    {
      "title": "Job Title",
      "company": "Company Name",
      "location": "City",
      "period": "Jan 2024 - Dec 2024",
      "bullets": [
        "Achievement bullet 1 — quantified impact",
        "Achievement bullet 2"
      ],
      "title_variants": [
        {
          "variant_id": "support",
          "title": "Alternative title (e.g. Support Engineer)",
          "triggers": ["support", "helpdesk", "N2"],
          "bullets": ["Adapted bullets for this variant"]
        }
      ]
    }
  ],
  "education": [
    {
      "degree": "Degree name",
      "school": "School name",
      "location": "City",
      "year": "2022",
      "details": "Specialisation or relevant detail"
    }
  ],
  "certifications": [
    {
      "name": "Certification name",
      "issuer": "Issuer",
      "status": "obtenu | en cours"
    }
  ],
  "skills": [
    { "label": "Réseaux", "value": "TCP/IP" },
    { "label": "Réseaux", "value": "VLAN" },
    { "label": "Programmation", "value": "Python" }
  ],
  "projects": [
    {
      "name": "Project Name",
      "tech": ["Python", "FastAPI"],
      "description": "190–230 char ATS-friendly description of what it does and why it matters."
    }
  ],
  "languages": [
    { "label": "Français", "value": "Natif" },
    { "label": "Anglais", "value": "Courant" }
  ]
}
```

**`skills` rules:** flat array of `{label, value}` pairs. `value` = one skill name, max 28 chars. Same `label` for all skills in the same category. 20–31 entries total. No `soft_skills` key.

**`title_variants`:** lets the AI swap the job title and bullets when the offer matches certain keywords. Leave `[]` if you don't need variants for a role.

---

#### `cv_main_en.json` — English base CV template

Same structure as `cv_main.json` but:
- Add `"_lang": "en"` as a root key
- Translate all French text to English
- Use `expert / advanced / proficient / intermediate / basic` for skill values

---

#### `cv_master_profile.json` — Full candidate profile

Source of truth for cover letter generation and project selection. Include everything — more detail gives the AI better material to work with.

```json
{
  "identity": {
    "full_name": "Your Name",
    "email": "you@example.com",
    "phone": "...",
    "linkedin": "...",
    "github": "...",
    "address": "..."
  },
  "experience": [
    {
      "title": "Job Title",
      "company": "Company",
      "location": "City",
      "period": "...",
      "bullets": ["short bullet 1", "short bullet 2"],
      "missions": [
        "Full sentence describing a specific mission, what you did and how, up to 200 chars."
      ]
    }
  ],
  "projects": [
    {
      "name": "Project Name",
      "tech": ["Python", "Docker"],
      "description": "What it does, the problem it solves, and results achieved.",
      "keywords": ["automation", "monitoring", "homelab"]
    }
  ],
  "skills": {
    "Networks": {
      "items": ["TCP/IP", "BGP", "OSPF", "VLAN", "Firewall"]
    },
    "Programming": {
      "items": ["Python", "Bash", "SQL"]
    }
  },
  "keywords": {
    "cybersecurity": ["SOC", "SIEM", "Splunk", "Suricata", "IDS", "EDR"],
    "networking":    ["TCP/IP", "BGP", "OSPF", "VLAN", "switch", "routeur"]
  }
}
```

`skills` here is a categorised dict (different schema from `cv_main.json`). `keywords` categories match your target job domains — 8–15 keywords each.

---

#### `user_config.json` — Prompt configuration

Controls how the AI picks your job title and writes your cover letters. Edit this file (not `backend.py`) when adapting the tool to a new user.

```json
{
  "_comment": "Edit this file to adapt the CV generator to a new user.",
  "identity": {
    "gender": "homme | femme",
    "tagline_prefix": "Your main professional identity in French (e.g. Développeur Full Stack)"
  },
  "owned_titles": {
    "fr": [
      { "title": "Ingénieur Réseaux",  "triggers": ["réseau", "LAN", "WAN", "switch", "VLAN"] },
      { "title": "Développeur Python", "triggers": ["Python", "FastAPI", "scripting"] }
    ],
    "en": [
      { "title": "Network Engineer",   "triggers": ["network", "LAN", "WAN", "switch", "VLAN"] },
      { "title": "Python Developer",   "triggers": ["Python", "FastAPI", "scripting"] }
    ]
  },
  "summary_examples": [
    {
      "context": "poste SOC N2 / analyste cybersécurité",
      "text": "55–80 word first-person French summary for this role type. No clichés — start with a concrete fact."
    },
    {
      "context": "poste développeur backend Python",
      "text": "Second example targeting a different role type."
    },
    {
      "context": "poste chef de projet technique",
      "text": "Third example."
    }
  ]
}
```

`owned_titles` — add every role you can legitimately claim. The AI picks the best match per job offer and uses it as the CV title, or builds a "reconversion" title if the offer is in a domain you're transitioning into.

---

## Quick start (after profile setup)

### 1. Get a Groq API key

1. Go to [console.groq.com](https://console.groq.com) and create a free account
2. Navigate to **API Keys** → **Create API key**
3. Copy the key (starts with `gsk_...`)

Free tier is sufficient — the project uses `meta-llama/llama-4-scout-17b-16e-instruct`.

### 2. Clone and install

```bash
git clone <your-repo-url>
cd routine_job_hunt

python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file at the project root:

```env
Groq_API_text_analysis=gsk_your_key_here

# Optional — only needed for Google Sheets sync
GOOGLE_SHEET_ID=your_spreadsheet_id
```

### 4. Start the backend

```bash
uvicorn backend:app --port 8000 --reload
```

Verify it's running:
```
http://localhost:8000/health   →  { "status": "ok" }
http://localhost:8000          →  Application tracking dashboard
```

### 5. Install the Chrome extension

1. Open Chrome → go to `chrome://extensions`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `cv-extractor-v5/cv-extractor/` folder
5. The extension icon appears in your toolbar — click it to open the side panel

---

## Using the extension

1. Navigate to any job listing (LinkedIn, Indeed, Glassdoor, WTTJ, company careers page, etc.)
2. Open the side panel by clicking the extension icon
3. Choose your options:
   - **Generate**: CV only / Cover letter / Both
   - **Language**: French or English
   - **CV Style**: Two columns (classic) or One column (modern)
4. Click **Extract & Generate**
5. The backend generates the PDF in ~15 seconds — it appears in `CV_jobs/`

If extraction fails (rare, on heavily JS-rendered pages), a paste fallback appears — paste the job description text manually.

---

## Customising the prompts

All prompts live in `backend.py`.

### CV generation prompt

Search for `PATCH_PROMPT_SOC` — it's a multi-line string. This prompt controls:

- How the AI rewrites the job title (using `owned_titles` from `user_config.json`)
- How it selects and rewrites the 4 projects (X-Y method)
- How it reorders and relabels your skills (max 31 entries)
- How it injects a keyword bullet into the best experience
- How it picks the most relevant certification to highlight

User-specific content (tagline, owned titles, summary examples, gender) is injected automatically from `user_config.json` at startup — you don't need to edit the prompt string directly.

### Cover letter prompt

Search for `LETTER_PROMPT` in `backend.py`. The letter is generated from `cv_master_profile.json` via `_filter_profile()` which keyword-scores your experiences and projects against the job offer before passing them to Groq.

---

## PDF layout

Two renderers are available, both accept the same JSON schema:

| File | Layout |
|---|---|
| `generate_cv_last_version.py` | Two-column A4 (main content + right sidebar) |
| `generate_cv_one_column.py` | Single-column A4 (full width, modern) |

You can generate a PDF directly from any CV JSON file without starting the backend:

```bash
python generate_cv_last_version.py my_cv.json output.pdf
python generate_cv_one_column.py my_cv.json output.pdf
```

Fonts are in `fonts/` (OpenSans Regular + Bold). Replace them with any TTF to change the typeface — update the `pdfmetrics.registerFont` calls at the top of each renderer.

---

## Application tracking dashboard

The dashboard at `http://localhost:8000` shows every generated CV with status tracking.

Update application status via the dropdown (`cv_generated → applied → interview → offer → rejected → ghosted`). Status changes are saved to `suivi.json`.

### Google Sheets sync (optional)

1. Create a Google Cloud project and enable the Sheets API
2. Create a service account and download `google_credentials.json`
3. Place it at the project root
4. Share your target spreadsheet with the service account email
5. Add `GOOGLE_SHEET_ID=your_id` to `.env`
6. Run `python setup_sheets.py` to initialize the sheet headers

If `google_credentials.json` is absent, Sheets sync silently does nothing.

---

## ATS optimizer (standalone)

`ats_optimizer.py` runs an iterative scoring loop without needing the backend or extension. Useful for fine-tuning a CV for a specific offer.

```bash
python ats_optimizer.py
```

It runs up to 6 rounds targeting a 90%+ ATS score. Each round is saved to `ats_runs/`.

---

## Project structure

```
├── backend.py                  # FastAPI app — all routes, Groq orchestration
├── generate_cv_last_version.py # Two-column PDF renderer
├── generate_cv_one_column.py   # One-column PDF renderer
├── ats_optimizer.py            # Standalone ATS scoring loop
├── sheets.py                   # Google Sheets sync (no-op if creds absent)
├── setup_sheets.py             # One-time Sheets initialization
├── user_config.json            # Prompt config — owned titles, summaries (git-ignored)
├── cv_main.json                # Your French base CV (git-ignored)
├── cv_main_en.json             # Your English base CV (git-ignored)
├── cv_master_profile.json      # Full profile for letter generation (git-ignored)
├── suivi.json                  # Application log (git-ignored)
├── fonts/                      # OpenSans TTF files
├── CV_jobs/                    # Generated CV PDFs (git-ignored)
├── lettres/                    # Generated cover letter PDFs (git-ignored)
├── ats_runs/                   # ATS optimizer snapshots (git-ignored)
├── onboarding/
│   └── setup-cv-generator.md  # Claude skill for onboarding new users
└── cv-extractor-v5/
    └── cv-extractor/           # Chrome extension (Manifest V3)
        ├── manifest.json
        ├── background.js       # Side panel registration + tab relay
        ├── content.js          # Job description + title extraction
        ├── popup.html          # Side panel UI
        └── popup.js            # Side panel logic
```

---

## Dependencies

- **Groq** — free tier at [console.groq.com](https://console.groq.com), model: `meta-llama/llama-4-scout-17b-16e-instruct`
- **ReportLab** — PDF generation (no external tools needed)
- **FastAPI + Uvicorn** — local API server
- **Chrome 114+** — required for Side Panel API
