# CV Extractor — Chrome Extension

Extracts job posts from LinkedIn, Glassdoor, Indeed, Welcome to the Jungle
and more — outputs a clean JSON ready to send to the AI CV generation pipeline.

## Supported Platforms
- ✅ LinkedIn Jobs
- ✅ Glassdoor
- ✅ Indeed (FR + EN)
- ✅ Welcome to the Jungle (WTTJ)
- ✅ Hellowork
- ✅ Pôle Emploi
- ✅ APEC
- ✅ Generic fallback (any job board)

## Installation (Chrome / Edge)

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer Mode** (top right toggle)
3. Click **Load unpacked**
4. Select this `cv-extractor/` folder
5. Pin the extension to your toolbar

## Usage

1. Navigate to any job listing page
2. Click the ⚡ extension icon
3. Click **Extract Job Post**
4. Click **Copy JSON** or **Download**

## Output JSON Structure

```json
{
  "meta": {
    "extracted_at": "2026-04-09T...",
    "source_url": "https://linkedin.com/jobs/...",
    "platform": "linkedin"
  },
  "job": {
    "title": "Analyste Cybersécurité",
    "company": "...",
    "location": "Lyon, France",
    "contract_type": "CDI",
    "description": "...(full text)...",
    "required_skills": ["Splunk", "SIEM", "Agile SAFe", ...],
    "word_count": 312
  },
  "for_ai": {
    "instruction": "Use cv_master_profile.json + this job post...",
    "prompt_ready": "Job Title: ...\nCompany: ...\n\nFull Description:\n..."
  }
}
```

## AI CV Generation Workflow

```
[Browse LinkedIn] → [Click ⚡] → [Copy JSON]
        ↓
[Paste into Claude with cv_master_profile.json]
        ↓
[Get 450-word targeted CV]
        ↓
[python cv_from_json.py cv_targeted.json output.docx]
        ↓
✅ Ready CV in your folder
```

## Next Steps (Phase 2)
- Connect extension to local Python agent via WebSocket
- One-click: extract → send to agent → receive .docx automatically
- Agent uses Claude API + master_profile.json to generate the CV
