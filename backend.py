"""
backend.py — CV Generator API
Receives a job offer from the extension, calls Groq, generates a targeted CV PDF.
Run: uvicorn backend:app --port 8000
"""

import json, os, re, sys, uuid
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from groq import Groq

sys.path.insert(0, str(Path(__file__).parent))
from generate_cv_last_version import build_cv as render_pdf_two_col
from generate_cv_one_column   import build_cv as render_pdf_one_col
from sheets import append_application, update_status as sheets_update

def render_pdf(json_path: str, pdf_path: str, style: str = "two_col"):
    if style == "one_col":
        render_pdf_one_col(json_path, pdf_path)
    else:
        render_pdf_two_col(json_path, pdf_path)

load_dotenv()

BASE_DIR     = Path(__file__).parent
CV_JOBS_DIR  = BASE_DIR / "CV_jobs"
LETTRES_DIR  = BASE_DIR / "lettres"
MASTER_FILE  = BASE_DIR / "cv_master_profile.json"
SOC_CV_FILE  = BASE_DIR / "cv_main.json"
SUIVI_FILE   = BASE_DIR / "suivi.json"

# ── User config (editable without touching backend.py) ────────────────────────
_CONFIG_FILE = BASE_DIR / "user_config.json"
if _CONFIG_FILE.exists():
    _USER_CFG = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
else:
    _USER_CFG = {}

def _cfg(path: str, default=""):
    """Dot-path accessor for _USER_CFG. e.g. _cfg('identity.gender')"""
    node = _USER_CFG
    for key in path.split("."):
        if not isinstance(node, dict):
            return default
        node = node.get(key, default)
    return node if node != {} else default

def _build_prompt_blocks() -> dict:
    """Build the user-specific blocks injected into PATCH_PROMPT_SOC."""
    gender     = _cfg("identity.gender", "homme")
    tl_prefix  = _cfg("identity.tagline_prefix", "Ingénieur")
    titles_fr  = _cfg("owned_titles.fr", [])
    titles_en  = _cfg("owned_titles.en", [])
    examples   = _cfg("summary_examples", [])

    gender_rule = (
        f"CANDIDAT : {gender} — accorder tous les adjectifs et participes au masculin "
        f"(ex: \"motivé\", \"confirmé\", \"reconverti\", \"passionné\")."
        if gender == "homme" else
        f"CANDIDAT : {gender} — accorder tous les adjectifs et participes au féminin "
        f"(ex: \"motivée\", \"confirmée\", \"reconvertie\", \"passionnée\")."
    )

    tagline_rule = (
        f'tagline : phrase courte en 2 parties séparées par " · " :\n'
        f'• Partie 1 : TOUJOURS "{tl_prefix}" — ne jamais modifier cette partie.\n'
        f'• Partie 2 : "passionné par [domaine principal de l\'offre]" — adapter selon l\'offre '
        f'(ex: "la cybersécurité", "l\'IA et le machine learning", "le DevOps et l\'automatisation")\n'
        f'→ max 80 caractères, naturel et professionnel, jamais générique.\n'
        f'Exemple : "{tl_prefix} · passionné par la cybersécurité"'
    )

    def _fmt_titles(titles):
        return " | ".join(f'"{t["title"]}"' for t in titles)

    def _fmt_triggers(titles):
        lines = []
        for t in titles:
            kws = "/".join(t["triggers"][:6])
            lines.append(f'  • Offre {kws} → "{t["title"]}"')
        return "\n".join(lines)

    owned_block = (
        f'TITRES POSSÉDÉS (pour display_title) :\n'
        f'FR : {_fmt_titles(titles_fr)}\n'
        f'EN : {_fmt_titles(titles_en)}\n\n'
        f'Règle display_title :\n'
        f'ÉTAPE A — Trouver le titre possédé le plus proche du poste :\n'
        f'{_fmt_triggers(titles_fr)}\n\n'
        f'ÉTAPE B — Décider si "en reconversion" est nécessaire :\n'
        f'  Si le titre possédé retenu couvre DIRECTEMENT le cœur du poste → retourner le titre seul.\n'
        f'  Sinon → retourner : "<titre possédé> en reconversion vers <titre cible de l\'offre>"\n\n'
        f'RÈGLES STRICTES :\n'
        f'  • Toujours choisir dans la liste ci-dessus — ne jamais inventer un titre hors liste\n'
        f'  • Max 80 caractères au total\n'
        f'  • Langue : utiliser FR ou EN selon lang_instruction\n'
        f'  • "en reconversion vers" → français | "transitioning to" → anglais'
    )

    ex_block = "EXEMPLES DE BONS SUMMARIES (calibration de ton — ne pas copier) :\n\n"
    for ex in examples:
        ex_block += f'Pour un {ex["context"]} :\n"{ex["text"]}"\n\n'

    return {
        "gender_rule":   gender_rule,
        "tagline_rule":  tagline_rule,
        "owned_block":   owned_block,
        "summary_examples_block": ex_block.strip(),
    }

_PROMPT_BLOCKS = _build_prompt_blocks()

CV_JOBS_DIR.mkdir(exist_ok=True)
LETTRES_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ── Suivi helpers ─────────────────────────────────────────────────────────────

STATUSES = ["cv_generated", "applied", "interview", "offer", "rejected", "ghosted"]

def _load_suivi() -> list:
    if SUIVI_FILE.exists():
        return json.loads(SUIVI_FILE.read_text(encoding="utf-8"))
    return []

def _save_suivi(entries: list):
    SUIVI_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

def _append_suivi(entry: dict):
    entries = _load_suivi()
    entries.insert(0, entry)  # newest first
    _save_suivi(entries)

STATUS_COLORS = {
    "cv_generated": "#1A73E8",
    "applied":      "#8AB4F8",
    "interview":    "#F9AB00",
    "offer":        "#34A853",
    "rejected":     "#EA4335",
    "ghosted":      "#5F6368",
}

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Suivi Candidatures</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#0D1117;color:#E6EDF3;padding:24px}}
  h1{{font-size:18px;font-weight:600;margin-bottom:4px}}
  .subtitle{{font-size:12px;color:#7D8590;margin-bottom:20px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{text-align:left;padding:8px 12px;border-bottom:2px solid #21262D;color:#7D8590;
      font-size:11px;text-transform:uppercase;letter-spacing:.06em}}
  td{{padding:9px 12px;border-bottom:1px solid #161B22;vertical-align:middle}}
  tr:hover td{{background:#161B22}}
  .badge{{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;
           font-weight:600;cursor:pointer;border:none;color:#fff}}
  .cv-link{{font-family:monospace;font-size:11px;color:#8AB4F8;word-break:break-all}}
  .date{{color:#7D8590;font-size:11px;white-space:nowrap}}
  select{{background:#161B22;color:#E6EDF3;border:1px solid #21262D;
          border-radius:4px;padding:3px 6px;font-size:11px;cursor:pointer}}
  .stats{{display:flex;gap:12px;margin-bottom:18px;flex-wrap:wrap}}
  .stat{{background:#161B22;border:1px solid #21262D;border-radius:8px;
         padding:10px 16px;min-width:100px;text-align:center}}
  .stat-n{{font-size:22px;font-weight:700}}
  .stat-l{{font-size:10px;color:#7D8590;margin-top:2px}}
  .empty{{text-align:center;padding:40px;color:#7D8590;font-size:13px}}
</style>
</head>
<body>
<h1>📋 Suivi Candidatures</h1>
<p class="subtitle">Mise à jour automatique à chaque CV généré</p>
<div class="stats" id="stats"></div>
<table>
  <thead>
    <tr>
      <th>Date</th><th>Poste</th><th>Entreprise</th>
      <th>Plateforme</th><th>CV</th><th>Statut</th>
    </tr>
  </thead>
  <tbody id="tbody"></tbody>
</table>
<script>
const COLORS={cv_generated:"#1A73E8",applied:"#8AB4F8",interview:"#F9AB00",
              offer:"#34A853",rejected:"#EA4335",ghosted:"#5F6368"};
const STATUSES={json_placeholder};

async function load(){{
  const data = await fetch('/suivi').then(r=>r.json());
  const tbody = document.getElementById('tbody');

  if(!data.length){{
    tbody.innerHTML='<tr><td colspan="6" class="empty">Aucune candidature enregistrée</td></tr>';
    return;
  }}

  // Stats
  const counts={{}};
  data.forEach(e=>{{ counts[e.status]=(counts[e.status]||0)+1; }});
  const statsEl=document.getElementById('stats');
  [['Total',data.length,'#E6EDF3'],
   ['Interview',counts.interview||0,COLORS.interview],
   ['Offre',counts.offer||0,COLORS.offer],
   ['Rejeté',counts.rejected||0,COLORS.rejected]
  ].forEach(([l,n,c])=>{{
    statsEl.innerHTML+=`<div class="stat"><div class="stat-n" style="color:${{c}}">${{n}}</div>
    <div class="stat-l">${{l}}</div></div>`;
  }});

  tbody.innerHTML = data.map(e => `
    <tr>
      <td class="date">${{e.date}}</td>
      <td><strong>${{e.role}}</strong></td>
      <td>${{e.company}}</td>
      <td style="font-size:11px;color:#7D8590">${{e.platform||'—'}}</td>
      <td><a class="cv-link" href="#" title="${{e.cv_path}}">${{e.cv_file}}</a></td>
      <td>
        <select onchange="setStatus('${{e.id}}',this.value)"
                style="background:${{COLORS[e.status]}}22;border-color:${{COLORS[e.status]}}">
          ${{STATUSES.map(s=>
            `<option value="${{s}}" ${{s===e.status?'selected':''}}>${{{{'cv_generated':'📄 CV généré',
            applied:'📤 Postulé',interview:'🎯 Entretien',offer:'🎉 Offre',
            rejected:'❌ Refusé',ghosted:'👻 Ghosté'}}[s]||s}}</option>`
          ).join('')}}
        </select>
      </td>
    </tr>`).join('');
}}

async function setStatus(id, status){{
  await fetch(`/suivi/${{id}}`, {{method:'PATCH',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{status}})
  }});
}}

load();
</script>
</body>
</html>"""


# ── Pydantic models ────────────────────────────────────────────────────────────

class JobPayload(BaseModel):
    meta: dict = {}
    job:  dict = {}
    for_ai: dict = {}

class StatusUpdate(BaseModel):
    status: str
    notes: str = ""


def _job_tokens(job_desc: str) -> set[str]:
    """Lowercase word-tokens from job description, 4+ chars, no punctuation."""
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9_\-]{4,}", job_desc.lower())
    # Drop generic French stop-words
    stop = {"pour","avec","dans","vous","nous","votre","notre","les","des",
            "une","sont","sera","cette","avoir","être","plus","très","comme",
            "aussi","tout","bien","leur","leurs","même","dont","mais","donc",
            "that","with","will","from","your","have","this","been","they"}
    return {w for w in words if w not in stop}


def _score(text: str, tokens: set[str]) -> int:
    """Count how many job tokens appear in a text blob."""
    blob = text.lower()
    return sum(1 for t in tokens if t in blob)


def _filter_profile(cv: dict, job_desc: str) -> dict:
    """
    A+B: strip noise fields (A) + keyword-score and slice experiences,
    projects and skill categories so only the most relevant reach Groq (B).
    """
    tokens = _job_tokens(job_desc)

    def _text(obj) -> str:
        """Flatten any JSON object to a single string for scoring."""
        return json.dumps(obj, ensure_ascii=False)

    def strip_meta(obj):
        if isinstance(obj, dict):
            return {k: strip_meta(v) for k, v in obj.items()
                    if k not in ("keywords", "id", "extended_description",
                                 "core_subjects", "skills_validated",
                                 "issuer_url", "source_url")}
        if isinstance(obj, list):
            return [strip_meta(i) for i in obj]
        return obj

    # ── Experiences: ALL, sorted by relevance (most relevant first) ───────────
    exps = cv.get("experience", [])
    scored_exps = sorted(exps, key=lambda e: _score(_text(e), tokens), reverse=True)
    top_exps = strip_meta(scored_exps)   # keep all, Groq will include all

    # Trim each mission to first 200 chars to stay token-efficient
    for exp in top_exps:
        for m in exp.get("missions", []):
            if isinstance(m, dict) and len(m.get("description", "")) > 200:
                m["description"] = m["description"][:200] + "…"

    # ── Projects: keep top 3 by score ─────────────────────────────────────────
    projs = cv.get("projects", [])
    scored_projs = sorted(projs, key=lambda p: _score(_text(p), tokens), reverse=True)
    top_projs = strip_meta(scored_projs[:5])

    # ── Skills: flat list or dict of categories ───────────────────────────────
    skills_raw = cv.get("skills", [])
    if isinstance(skills_raw, list):
        filtered_skills = [s for s in skills_raw if _score(s.get("label", ""), tokens) > 0] or skills_raw[:10]
    else:
        filtered_skills = {}
        for cat_key, cat_val in skills_raw.items():
            if not isinstance(cat_val, dict):
                continue
            matching = [i for i in cat_val.get("items", []) if _score(_text(i), tokens) > 0]
            all_items = cat_val.get("items", [])
            kept = matching if matching else all_items[:2]
            filtered_skills[cat_key] = {**{k: v for k, v in cat_val.items() if k != "items"},
                                         "items": strip_meta(kept)}

    # ── Certifications: all (usually only 4-5) ────────────────────────────────
    certs = strip_meta([
        {k: v for k, v in c.items() if k in ("name","issuer","year","status")}
        for c in cv.get("certifications", [])
    ])

    identity = strip_meta(cv.get("identity", {}))
    # Drop extended location fields not needed in the CV
    identity.pop("keywords", None)

    profile_raw = cv.get("profile", {})
    return {
        "identity":       identity,
        "profile": {
            "summary_fr":       profile_raw.get("summary_fr", ""),
            "hardware_keywords": profile_raw.get("keywords", []),
        },
        "experience":     top_exps,
        "education":      strip_meta(cv.get("education", [])),
        "skills":         filtered_skills,
        "certifications": certs,
        "projects":       top_projs,
        "languages":      cv.get("languages", []),
    }


PATCH_PROMPT_SOC = """\
Expert ATS. Objectif : faire passer le CV par les filtres ATS à 90%+. Retourne UNIQUEMENT 9 champs en JSON.
RÈGLE GLOBALE : chaque mot généré doit être utile — zéro remplissage, zéro répétition, zéro formule creuse. Maximum de sens par minimum de mots.
{gender_rule}
LANGUE : {lang_instruction}

OFFRE: {job_description}

ÉTAPE 0 — EXTRACTION ENTREPRISE (à faire EN PREMIER) :
{hint_block}
Lire l'offre en entier. Identifier l'entreprise qui recrute directement (pas le client final).
Chercher dans cet ordre de priorité :
1. Nom présent dans les métadonnées ou le titre de la page (souvent dans les 5 premiers mots sur LinkedIn)
2. Mentions explicites : "Rejoignez [Nom]", "[Nom] recrute", "Intégrez [Nom]", "[Nom] est une société"
3. Section "Qui sommes-nous" ou "À propos"
4. Signature ou bas de l'offre

RÈGLES STRICTES :
• Retourner le nom commercial exact tel qu'il apparaît dans l'offre
• Si l'offre mentionne "Groupe X" et "X Telecom" → prendre "X Telecom" (entité qui recrute)
• Si une ESN place chez un client → retourner le nom de l'ESN, pas du client
• Max 30 caractères, nom propre uniquement, sans "Société", "Groupe", "la", "les"
• Si vraiment introuvable → ""
Exemples : offre FACTORIA TELECOM → "FACTORIA TELECOM" ✓ | Capgemini pour client BNP → "Capgemini" ✓ | "Groupe Factoria - FACTORIA TELECOM" → "FACTORIA TELECOM" ✓

ÉTAPE 1 — MOTS-CLÉS TECHNIQUES (obligatoire) :
Lire l'offre en entier. Dresser mentalement la liste exhaustive de TOUS les mots-clés techniques : outils, langages, frameworks, protocoles, certifications, méthodologies (ex: CI/CD, MLOps, Docker, Kubernetes, Python, FastAPI, Terraform…). Cette liste est la référence absolue. Chaque élément de cette liste DOIT apparaître dans le CV final — soit dans skills, soit dans les descriptions projets, soit dans le keyword_bullet. Aucun mot-clé technique de l'offre ne doit être absent du CV.

PROJETS DISPONIBLES (choisir 4): {projects_json}

COMPÉTENCES DE BASE: {skills_json}

TITRE ACTUEL: {current_title}

JSON de sortie — exactement ces 9 champs:
{{
  "company": "<nom de l'entreprise qui recrute, extrait à l'Étape 0 — ex: 'SARDEL Conseil'>",
  "display_title": "<voir règle display_title>",
  "tagline": "<voir règle tagline>",
  "title": "<titre exact du poste — 2 à 6 mots>",
  "summary": "<voir règle summary>",
  "best_cert": "<nom exact d'UNE certification parmi CERTIFICATIONS DISPONIBLES — celle qui correspond le mieux au poste. Recopier le champ 'name' tel quel. Si aucune n'est pertinente : \"\">",
  "projects": [
    {{"name": "<nom exact>", "tech": [...], "description": "<2 phrases ATS>"}},
    {{"name": "<nom exact>", "tech": [...], "description": "<2 phrases ATS>"}},
    {{"name": "<nom exact>", "tech": [...], "description": "<2 phrases ATS>"}},
    {{"name": "<nom exact>", "tech": [...], "description": "<2 phrases ATS>"}}
  ],
  "skills": [{{"label": "...", "value": "..."}}],
  "keyword_bullet": {{
    "exp_index": 0,
    "bullet": "<nouvelle ligne — mots-clés absents, max 110 chars>",
    "rewrite_index": 0,
    "rewrite_bullet": "<reformulation ATS de la bullet[rewrite_index] existante — même longueur, plus de mots-clés offre>"
  }},
  "experience_variants": [
    {{"exp_index": 0, "variant_id": "<deploy|support>"}}
  ]
}}

{owned_block}

CERTIFICATIONS DISPONIBLES (choisir la plus pertinente pour best_cert) :
{certs_json}
Règle best_cert : choisir la certification dont le domaine recoupe le mieux les exigences de l'offre.
Exemples : offre SOC/SIEM/threat → "SOC Level 1" | offre Azure/cloud/Microsoft → "Microsoft Azure Fundamentals" | offre sécurité Microsoft/Sentinel → "SC-200: Microsoft Security Operations Analyst"
Si plusieurs sont proches → prendre celle dont le statut est "Certifié"/"Certified" de préférence.

Règles:

{tagline_rule}

summary : 2-3 phrases, 55-80 mots. Ton : direct, concret, humain — comme si le candidat
se présentait en 20 secondes à quelqu'un qu'il vient de rencontrer dans un couloir.

RÈGLES DE TON :
• Parler à la première personne implicite (sans "Je suis") — ex: "Ingénieur réseaux de formation,
  j'ai basculé vers la sécurité défensive après..." ou "Issu d'une formation ingénieur télécom..."
• Une seule idée forte par phrase — pas de liste déguisée
• Montrer une trajectoire ou une logique, pas juste une liste de compétences
• Le dernier mot doit donner envie de lire la suite (accroche vers les expériences)

STRUCTURE SOUPLE (choisir la plus naturelle selon le profil et le poste) :
Option A — Trajectoire : D'où vient le candidat → ce qu'il fait maintenant → pourquoi ce poste
Option B — Réalisation forte : Commencer par la chose la plus impressionnante → contexte → projection
Option C — Problème/Solution : Le besoin du poste → ce que le candidat apporte concrètement

CONTRAINTES TECHNIQUES (non négociables) :
• Mentionner au moins 2 mots-clés techniques EXACTS de l'offre — intégrés naturellement, pas listés
• Aucun chiffre d'années inventé (cf. RÈGLE ANTI-MENSONGE)
• Pas de certification mentionnée sauf si elle est dans le profil ET directement liée au poste
• Maximum absolu : 80 mots — couper sans hésiter

INTERDIT (formules qui tuent la crédibilité) :
• "passionné(e) par", "motivé(e)", "dynamique", "rigoureux/rigoureuse"
• "à la recherche de nouveaux défis", "désireux(se) de rejoindre"
• "solides compétences en", "bonne maîtrise de", "fort(e) d'une expérience"
• Toute formule qu'on retrouverait dans 1000 autres CVs

{summary_examples_block}

RÈGLE ANTI-MENSONGE (priorité absolue) :
• Ne JAMAIS inventer des années d'expérience — utiliser UNIQUEMENT les dates présentes dans EXPÉRIENCES DISPONIBLES
• Ne JAMAIS mentionner un outil, une certification ou une technologie absente du profil candidat fourni
• Si l'offre demande "5 ans d'expérience" et que le candidat n'en a pas → ne pas écrire "5 ans", écrire la durée réelle ou reformuler sans chiffre (ex: "expérience en administration systèmes et réseaux")
• Si aucune expérience directe sur un point clé → mettre en avant les projets personnels ou la formation, jamais inventer
• Toute affirmation du summary doit être vérifiable dans le JSON profil fourni

ANCRAGE TEMPOREL OBLIGATOIRE :
Les expériences disponibles couvrent : {experience_dates}
Si tu mentionnes de l'expérience, utilise uniquement ces périodes comme référence. Ne jamais extrapoler une durée totale qui dépasserait la somme de ces périodes.

title: 2 à 6 mots maximum — uniquement le titre du poste, jamais une phrase ou mission.

projects (exactement 4) :

SÉLECTION — Score chaque projet disponible sur 3 critères, prendre les 4 meilleurs scores :
  1. Overlap stack/tech avec les technologies EXACTES citées dans l'offre (poids x3)
     → compter combien de termes de la stack du projet apparaissent textuellement dans l'offre
  2. Domaine métier cohérent avec le poste (poids x2)
     → cybersécurité, IA/ML, infrastructure, réseau, DevOps, data — choisir le plus proche du poste
  3. Complexité/impact du projet — préférer les projets avec résultat mesurable (poids x1)

RÈGLE DE DIVERSITÉ : les 4 projets retenus doivent couvrir au moins 2 domaines distincts.
Si les 4 meilleurs scores viennent tous du même domaine → remplacer le 4e par le meilleur projet d'un autre domaine.
Objectif : montrer un profil polyvalent ET pertinent pour le poste.

name + tech : recopier exactement depuis PROJETS DISPONIBLES, sans modifier.
tech : enrichir avec les mots-clés de l'offre que le projet couvre réellement (max +3 termes — priorité aux mots-clés non encore couverts par les skills).

DESCRIPTION — Méthode X-Y obligatoire (format Google résumé) :
  Phrase 1 (X-Y) : "Développé/Conçu/Implémenté [ce que le projet accomplit concrètement — X], réduisant/améliorant/atteignant [résultat mesurable ou impact qualitatif précis — Y]."
  Phrase 2 : Enchaîner les mots-clés EXACTS communs entre la stack du projet et l'offre — priorité aux mots-clés de l'offre non encore présents dans skills.
  • Longueur totale : 190-230 caractères. Maximum absolu : 230 caractères — couper sans hésiter.
  • Zéro formule vague ("solution robuste", "approche innovante", "de manière efficace").
  • Chaque projet doit mettre en avant un angle différent — ne pas répéter les mêmes mots-clés d'un projet à l'autre.

VALIDATION OBLIGATOIRE avant de répondre :
  1. Compter les caractères de chaque "description". Si > 230 → couper à la dernière phrase complète avant 230. Ne jamais tronquer en milieu de phrase.
  2. Vérifier que les 4 projets sont distincts (aucun doublon de nom).
  3. Vérifier la diversité de domaine (au moins 2 domaines différents représentés).

skills — exactement 10 entrées, format {{"label": "...", "value": "..."}} pour chacune.

PROCESSUS EN 3 ÉTAPES OBLIGATOIRES :

ÉTAPE A — MOTS-CLÉS OFFRE (max 5) : Les 5 mots-clés techniques les plus cités dans l'offre.
Règle label : nom propre ou acronyme reconnu ("Python", "CI/CD", "MLOps", "Kubernetes", "ISO 27001"). INTERDIT : mots communs isolés ("Data", "Engineer", "équipe"), verbes, adjectifs seuls, titres de poste.

ÉTAPE B — COMPÉTENCES CANDIDAT PERTINENTES (max 3) : Parmi COMPÉTENCES DE BASE, les 3 plus liées au domaine du poste. Ajouter après Étape A.

ÉTAPE C — COMPLÉTION JUSQU'À 10 (max 2) : 2 outils standards du domaine non encore listés (ex: ML Engineer → Git, MLflow ; SOC → Nmap, Wireshark ; Sysadmin → Bash, Ansible). Valeur = "confirmé".

CLASSEMENT FINAL : Étape A en premier, puis B, puis C. Total = 10 exactement.

RÈGLE DES VALEURS — distribution variée, jamais tout "confirmé" :
• "expert"        → technologie centrale du poste, citée plusieurs fois, cœur de métier du candidat
• "avancé"        → technologie importante dans l'offre, maîtrisée en contexte professionnel
• "confirmé"      → technologie mentionnée dans l'offre, utilisée régulièrement
• "intermédiaire" → technologie périphérique ou complémentaire (Étape C)
Distribution attendue sur 10 :  2-3 "avancé", 3-4 "confirmé", 2-3 "intermédiaire".

MOTS-CLÉS ABSENTS DU CV À COUVRIR OBLIGATOIREMENT: {missing_keywords}
keyword_bullet:
1. Lire les expériences ci-dessous et choisir la plus proche de l'offre → exp_index (0/1/2).
2. Lister tous les mots-clés techniques de l'offre (outils, produits, protocoles, technos).
3. Identifier lesquels sont ABSENTS des bullets existants de l'expérience choisie.
4. Écrire UNE phrase qui contient le maximum de ces mots-clés ABSENTS — pas ceux déjà présents.
Format : verbe passé + mots-clés absents enchaînés + contexte minimal. Max 110 caractères.
Exemple : si les bullets mentionnent déjà Hyper-V et VMware → ne pas les répéter → mettre Active Directory, GPO, DNS/DHCP, Proxmox, Zabbix à la place.

EXPÉRIENCES DISPONIBLES (dans l'ordre):
{experiences_json}

experience_variants :
RÈGLE STRICTE : ne retourner une entrée QUE pour un exp_index dont le champ "title_variants" dans EXPÉRIENCES DISPONIBLES est NON VIDE.
Si title_variants est absent ou vide pour une expérience → ne JAMAIS l'inclure dans experience_variants.

Pour chaque expérience qui possède un "title_variants" non vide :
  1. Compter combien de "triggers" de chaque variante apparaissent TEXTUELLEMENT dans l'offre (insensible à la casse)
  2. Choisir la variante avec le score le plus élevé
  3. En cas d'égalité → choisir la variante dont le "title" ressemble le plus au titre du poste
  4. Si score = 0 pour toutes les variantes → ne pas inclure cette expérience

Indices avec title_variants : {variant_indices}
Retourner [] si aucun de ces indices n'a de score > 0.

NE PAS retourner de champ "experience" ou "soft_skills". Uniquement : company, tagline, title, summary, projects, skills, keyword_bullet, experience_variants.
"""

LETTER_PROMPT_TEMPLATE = """\
Tu rédiges une lettre de motivation professionnelle en français. Percutante, authentique, sans formules creuses.

═══ OFFRE D'EMPLOI ═══
{job_description}

═══ PROFIL CANDIDAT ═══
{master_profile}

═══ RÈGLES ═══
Structure en 4 paragraphes, 320-370 mots total :

§1 — ACCROCHE (4-5 lignes) :
- Montrer que tu comprends le défi/contexte de l'entreprise pour CE poste précis
- Une phrase qui prouve que tu as lu l'offre (mentionner une mission ou technologie spécifique)
- NE PAS commencer par "Je me permets de vous contacter..."

§2 — VALEUR AJOUTÉE (6-8 lignes) :
- 2-3 réalisations concrètes directement liées aux missions du poste
- Chiffres si disponibles, sinon impact qualitatif précis
- Utiliser les mots-clés EXACTS de l'offre naturellement intégrés
- Montrer la progression logique : contexte → action → résultat

§3 — INITIATIVE PERSONNELLE (5-6 lignes) :
- Choisir UN projet personnel du profil candidat qui résonne directement avec les besoins du poste (homelab, outil construit, automatisation, déploiement perso...)
- Montrer que le candidat ne se contente pas de connaître les technos — il les met en œuvre, il livre : décrire ce qui a été concrètement construit, configuré ou automatisé
- Angle : autodidacte qui prend des initiatives en dehors du cadre professionnel pour aller plus loin
- NE PAS décrire une intention ou une curiosité — décrire un résultat concret (ce qui tourne, ce qui a été déployé, ce qui résout un vrai problème)
- Ton : direct et factuel — "j'ai construit / déployé / automatisé", pas "je m'efforce" ni "je cherche à"

§4 — ADÉQUATION + APPEL À L'ACTION (4-5 lignes) :
- Ce que CE poste t'apporte (développement, défi, environnement) — pas générique
- Formule de clôture directe et confiante, pas obséquieuse
- Proposer un entretien de façon assertive

FORMAT :
- Commencer par : "Madame, Monsieur,"
- Terminer par : "Dans l'attente de votre retour, je reste disponible pour un entretien.\\n\\nCordialement,\\n{candidate_name}"
- NE PAS inventer de faits absents du profil
- Ton : professionnel mais humain — pas de langue de bois

Réponds en JSON avec exactement ces trois champs :
{{
  "company": "Nom exact de l'entreprise recruteuse (extrait de l'offre, sans mention H/F ni intitulé de poste)",
  "role": "Intitulé exact du poste (extrait de l'offre, sans mention H/F)",
  "letter": "Le texte complet de la lettre"
}}
"""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    html = DASHBOARD_HTML.replace(
        "{json_placeholder}",
        json.dumps(STATUSES)
    )
    return HTMLResponse(html)


@app.get("/suivi")
def get_suivi():
    return _load_suivi()


@app.patch("/suivi/{entry_id}")
def update_status(entry_id: str, body: StatusUpdate):
    if body.status not in STATUSES:
        raise HTTPException(400, f"Status invalide. Valeurs: {STATUSES}")
    entries = _load_suivi()
    for e in entries:
        if e["id"] == entry_id:
            e["status"] = body.status
            if body.notes:
                e["notes"] = body.notes
            e["updated_at"] = datetime.now().isoformat()
            _save_suivi(entries)
            sheets_update(entry_id, body.status, body.notes)
            return e
    raise HTTPException(404, "Entrée introuvable")


def payload_company_fallback(job_desc: str) -> str:
    """Extract company name from job description text as a best-effort fallback."""
    for pattern in (r"Entreprise\s*[:\-]\s*(.+)", r"Company\s*[:\-]\s*(.+)"):
        m = re.search(pattern, job_desc, re.IGNORECASE)
        if m:
            return m.group(1).strip().split("\n")[0][:50]
    return ""


# ── Display title builder ──────────────────────────────────────────────────────
# Maps keyword fragments (lowercase) → the canonical "owned" background title
_OWNED_ROLES_FR = [
    (["réseaux", "réseau", "telecom", "télécoms", "télécommunications", "rf", "5g", "antenne"],
     "Ingénieur Réseaux & Télécoms"),
    (["chef de projet", "project manager", "déploiement", "delivery", "pilotage", "coordination"],
     "Chef de Projet"),
    (["ia", " ai ", "machine learning", "deep learning", "computer vision", "nlp", "data science"],
     "Ingénieur IA & Data"),
    (["administrateur", "sysadmin", "admin sys", "systèmes", "infrastructure", "vmware", "hyper-v"],
     "Administrateur Systèmes & Réseaux"),
    (["support", "helpdesk", "n2", "n3", "itsm", "itil", "service desk"],
     "Ingénieur Support N2"),
]

_OWNED_ROLES_EN = [
    (["network", "telecom", "telecommunication", "rf", "5g", "antenna"],
     "Network & Telecom Engineer"),
    (["project manager", "deployment", "delivery", "coordination", "rollout"],
     "Project Manager"),
    (["ai", "machine learning", "deep learning", "computer vision", "nlp", "data science"],
     "AI & Data Engineer"),
    (["sysadmin", "system administrator", "infrastructure", "vmware", "hyper-v"],
     "Systems & Network Administrator"),
    (["support", "helpdesk", "n2", "n3", "itsm", "itil", "service desk"],
     "N2 Support Engineer"),
]


def _build_display_title(target_role: str, lang: str = "fr") -> str:
    """
    Build a smart one-line title:
      - If target matches an owned role → just that role title
      - Otherwise → "<best background> en reconversion vers <target>"
    """
    if not target_role:
        return "Ingénieur Réseaux & Télécoms" if lang != "en" else "Network & Telecom Engineer"

    needle = target_role.lower()
    buckets = _OWNED_ROLES_EN if lang == "en" else _OWNED_ROLES_FR

    # Check if target IS one of the owned roles
    for keywords, label in buckets:
        if any(kw in needle for kw in keywords):
            return label

    # Target is not an owned role → pick best background and append reconversion
    # Default background: first experience title (most recent role)
    background = buckets[0][1]  # Ingénieur Réseaux & Télécoms by default

    if lang == "en":
        return f"{background}, transitioning to {target_role}"
    else:
        return f"{background} en reconversion vers {target_role}"


def _patch_cv_soc(master_cv: dict, soc_base: dict, job_desc: str, client: Groq, lang: str = "fr", hint_company: str = "") -> tuple[dict, dict]:
    """
    Patch 3 things on the soc-cv template:
      - identity.title  (copied from job offer)
      - projects        (2 chosen from master pool, descriptions ATS-enriched)
      - skills          (reordered/relabelled from the existing soc-cv skill list)
    Everything else stays untouched.
    """
    import copy
    cv = copy.deepcopy(soc_base)

    tokens = _job_tokens(job_desc)

    # Project pool: score master profile projects, convert to soc format, take top 5
    master_projs = master_cv.get("projects", [])
    scored = sorted(
        master_projs,
        key=lambda p: _score(json.dumps(p, ensure_ascii=False), tokens),
        reverse=True,
    )
    candidates = [
        {
            "name":        p.get("name", ""),
            "tech":        p.get("tech", []),
            "description": p.get("description", p.get("summary", "")),
        }
        for p in scored[:10]
        if p.get("name")
    ]
    # Append any soc-base projects not already in the pool
    pool_names = {p["name"] for p in candidates}
    for p in soc_base.get("projects", []):
        if p.get("name") not in pool_names:
            candidates.append(p)

    current_title = soc_base.get("identity", {}).get("title", "")
    skills_pool   = soc_base.get("skills", [])

    # Extract technical keywords: job tokens that exist in the master keywords bank
    # but are absent from the current soc_base — ensures only real tech terms are passed
    master_kw_bank = set()
    for cat in master_cv.get("keywords", {}).values():
        if isinstance(cat, list):
            for kw in cat:
                master_kw_bank.update(kw.lower().split())
    cv_blob = json.dumps(soc_base, ensure_ascii=False).lower()
    if master_kw_bank:
        missing_kw = [t for t in sorted(tokens)
                      if t in master_kw_bank and t not in cv_blob][:10]
    else:
        tech_stop = {"avec", "dans", "pour", "vous", "nous", "votre", "notre",
                     "sera", "sont", "cette", "avoir", "etre", "plus", "tres"}
        missing_kw = [t for t in sorted(tokens)
                      if len(t) >= 5 and t not in cv_blob and t not in tech_stop][:10]

    experience_dates = " | ".join(
        f"{e.get('title','?')} @ {e.get('company','?')} ({e.get('period','?')})"
        for e in soc_base.get("experience", [])
    )

    experiences_summary = [
        {
            "index":          i,
            "title":          e.get("title", ""),
            "company":        e.get("company", ""),
            "bullets":        e.get("bullets", [])[:3],
            "title_variants": [
                {"variant_id": v["variant_id"], "title": v["title"], "triggers": v["triggers"]}
                for v in e.get("title_variants", [])
            ],
        }
        for i, e in enumerate(soc_base.get("experience", []))
    ]

    lang_instruction = (
        "Reply ENTIRELY in English. Skill values in English: expert/advanced/proficient/intermediate/basic."
        if lang == "en" else
        "Réponds ENTIÈREMENT en français. Valeurs de compétences : expert/avancé/confirmé/intermédiaire/notions."
    )

    hint_block = (
        f'HINT ENTREPRISE (détecté par l\'extension) : "{hint_company}" — utiliser sauf si l\'offre contredit clairement ce nom.\n'
        if hint_company else ""
    )

    # Pre-compute which indices actually have variants (passed to the prompt)
    variant_indices = [
        str(i) for i, e in enumerate(soc_base.get("experience", []))
        if e.get("title_variants")
    ]

    blocks = _PROMPT_BLOCKS
    prompt = PATCH_PROMPT_SOC.format(
        job_description         = job_desc,
        projects_json           = json.dumps(candidates, ensure_ascii=False),
        skills_json             = json.dumps(skills_pool, ensure_ascii=False),
        current_title           = current_title,
        missing_keywords        = ", ".join(missing_kw) if missing_kw else "aucun",
        experiences_json        = json.dumps(experiences_summary, ensure_ascii=False),
        lang_instruction        = lang_instruction,
        hint_block              = hint_block,
        experience_dates        = experience_dates,
        variant_indices         = ", ".join(variant_indices) if variant_indices else "aucun",
        certs_json              = json.dumps(
            [{"name": c["name"], "issuer": c.get("issuer",""), "status": c.get("status","")}
             for c in soc_base.get("certifications", [])],
            ensure_ascii=False
        ),
        gender_rule             = blocks["gender_rule"],
        tagline_rule            = blocks["tagline_rule"],
        owned_block             = blocks["owned_block"],
        summary_examples_block  = blocks["summary_examples_block"],
    )

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model           = "meta-llama/llama-4-scout-17b-16e-instruct",
                messages        = [{"role": "user", "content": prompt}],
                response_format = {"type": "json_object"},
                max_tokens      = 1600,
                temperature     = 0.45 + attempt * 0.05,
            )
            break
        except Exception as e:
            if attempt == 2:
                raise
            continue

    patch = json.loads(response.choices[0].message.content)
    (BASE_DIR / "_last_patch.json").write_text(
        json.dumps({
            "patch":            patch,
            "variant_applied":  patch.get("experience_variants", []),
            "missing_kw_sent":  missing_kw,
            "projects_pool":    [p["name"] for p in candidates],
            "skills_pool_size": len(skills_pool),
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if patch.get("title"):
        t = patch["title"].strip()
        if len(t) <= 60 and t.count(" ") <= 8:
            cv["_target_title"] = t

    if patch.get("display_title"):
        dt = patch["display_title"].strip()
        if 2 < len(dt) <= 80:
            cv["_display_title"] = dt

    if patch.get("best_cert"):
        cert_name = patch["best_cert"].strip()
        matched = next((c for c in cv.get("certifications", []) if c["name"] == cert_name), None)
        if matched:
            status = matched.get("status", "")
            cv["_display_cert"] = f"{matched['name']} — {matched['issuer']} ({status})"

    if patch.get("projects"):
        cv["projects"] = [
            {
                "name":        p.get("name", ""),
                "tech":        p.get("tech", []),
                "description": p.get("description", ""),
            }
            for p in patch["projects"][:3]
        ]

    if patch.get("skills"):
        ordered = []
        seen = set()
        for s in patch["skills"]:
            lbl = s.get("label", "")
            val = s.get("value", "")
            if not lbl or lbl in seen:
                continue
            seen.add(lbl)
            ordered.append({"label": lbl, "value": val[:28]})
        for s in skills_pool:
            if s["label"] not in seen and len(ordered) < 10:
                ordered.append({"label": s["label"], "value": s["value"]})
        cv["skills"] = ordered[:10]

    if patch.get("summary"):
        summary = patch["summary"].strip()
        exp_years = len(soc_base.get("experience", []))
        fake_exp = re.search(r'(\d+)\s*ans?\s*d.expérience', summary, re.IGNORECASE)
        if fake_exp and int(fake_exp.group(1)) > exp_years + 1:
            summary = re.sub(r'[^.]*\d+\s*ans?\s*d.expérience[^.]*\.?\s*', '', summary, flags=re.IGNORECASE).strip()
        if summary:
            cv.setdefault("profile", {})["summary_fr"] = summary

    cv.pop("soft_skills", None)

    # Track which variant-capable experiences were handled by Groq
    groq_handled = set()
    job_desc_lower = job_desc.lower()

    for variant_choice in patch.get("experience_variants", []):
        v_idx = variant_choice.get("exp_index")
        v_id  = variant_choice.get("variant_id")
        if not isinstance(v_idx, int) or not v_id:
            continue
        if v_idx >= len(cv.get("experience", [])):
            continue
        exp = cv["experience"][v_idx]
        if not exp.get("title_variants"):
            continue  # Groq hallucinated a variant on an experience that has none
        chosen = next((v for v in exp["title_variants"] if v["variant_id"] == v_id), None)
        if chosen:
            exp["title"]   = chosen["title"]
            exp["bullets"] = chosen["bullets"]
            groq_handled.add(v_idx)

    # Python-side fallback: score any variant-capable experience Groq missed or got wrong
    for i, exp in enumerate(cv.get("experience", [])):
        if i in groq_handled or not exp.get("title_variants"):
            continue
        best_variant = None
        best_score   = 0
        for v in exp["title_variants"]:
            score = sum(1 for t in v["triggers"] if t.lower() in job_desc_lower)
            if score > best_score:
                best_score   = score
                best_variant = v
        if best_variant and best_score > 0:
            exp["title"]   = best_variant["title"]
            exp["bullets"] = best_variant["bullets"]

    kb         = patch.get("keyword_bullet", {})
    kb_exp_idx = kb.get("exp_index")

    if isinstance(kb_exp_idx, int) and 0 <= kb_exp_idx < len(cv.get("experience", [])):
        kb_exp = cv["experience"][kb_exp_idx]

        if kb.get("rewrite_bullet") and isinstance(kb.get("rewrite_index"), int):
            r_idx = kb["rewrite_index"]
            if 0 <= r_idx < len(kb_exp.get("bullets", [])):
                kb_exp["bullets"][r_idx] = kb["rewrite_bullet"].strip()[:150]

        if kb.get("bullet"):
            kb_exp["bullets"].append(kb["bullet"].strip()[:110])

    ai_company = (patch.get("company") or "").strip()
    meta = {
        "target_role":    patch.get("title", current_title),
        "target_company": ai_company if ai_company else payload_company_fallback(job_desc),
        "tagline":        (patch.get("tagline") or "").strip(),
    }
    return cv, meta


@app.post("/generate-cv")
async def generate_cv(payload: JobPayload):
    if not MASTER_FILE.exists():
        raise HTTPException(500, "cv_master_profile.json introuvable")
    if not SOC_CV_FILE.exists():
        raise HTTPException(500, "cv_main.json introuvable")

    lang_early = payload.meta.get("lang", "fr")
    en_cv_file = BASE_DIR / "cv_main_en.json"
    soc_cv_src = en_cv_file if lang_early == "en" and en_cv_file.exists() else SOC_CV_FILE

    with open(MASTER_FILE, encoding="utf-8") as f:
        master = json.load(f)
    with open(soc_cv_src, encoding="utf-8") as f:
        soc_base = json.load(f)

    master_cv = master
    job_desc  = payload.job.get("description", "") or payload.for_ai.get("prompt_ready", "")
    lang      = payload.meta.get("lang", "fr")   # "en" sent by extension for English CVs
    cv_style  = payload.meta.get("style", "two_col")  # "one_col" | "two_col"

    if not job_desc:
        raise HTTPException(400, "Description du poste vide")

    # Save last job offer for inspection
    (BASE_DIR / "_last_joboffer.json").write_text(
        json.dumps({"description": job_desc, "meta": payload.meta, "job": payload.job},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )

    client = Groq(api_key=os.getenv("Groq_API_text_analysis"))
    hint_company = payload.meta.get("company", "") or payload.job.get("company", "")
    cv_out, cv_meta = _patch_cv_soc(master_cv, soc_base, job_desc, client, lang=lang, hint_company=hint_company)

    detected_company = cv_meta.get("target_company", "")
    if not detected_company:
        print("[WARN] Company extraction failed — check _last_patch.json")
    elif len(detected_company) > 30:
        print(f"[WARN] Company name suspiciously long: '{detected_company}'")

    # Build filename from role + company
    role     = re.sub(r'[^\w\s-]', '', cv_meta.get("target_role", "role")).strip().replace(" ", "_")[:40]
    company  = re.sub(r'[^\w\s-]', '', cv_meta.get("target_company", "company")).strip().replace(" ", "_")[:30]
    today    = date.today().strftime("%Y-%m-%d")
    basename = f"{role}_{company}_{today}"

    tmp_json = BASE_DIR / f"_tmp_{basename}.json"
    pdf_path = str(CV_JOBS_DIR / f"{basename}.pdf")

    # Save last generated CV JSON for inspection
    cv_out["_lang"] = lang
    cv_out["_company"] = cv_meta.get("target_company", "")
    cv_out["_tagline"] = cv_meta.get("tagline", "")
    cv_out["_target_title"] = cv_meta.get("target_role", "")
    # Groq sets _display_title inside _patch_cv_soc via the display_title field.
    # Fall back to Python computation only if it came back empty.
    if not cv_out.get("_display_title"):
        cv_out["_display_title"] = _build_display_title(
            cv_meta.get("target_role", ""), lang
        )

    debug_json = BASE_DIR / "_last_generated_cv.json"
    debug_json.write_text(json.dumps(cv_out, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(cv_out, f, ensure_ascii=False, indent=2)

        render_pdf(str(tmp_json), pdf_path, style=cv_style)
        output_file = f"{basename}.pdf"
        output_path = pdf_path

    finally:
        if tmp_json.exists():
            tmp_json.unlink()

    # ── Log to suivi ──────────────────────────────────────────────────────────
    suivi_entry = {
        "id":         str(uuid.uuid4()),
        "date":       today,
        "role":       cv_meta.get("target_role", ""),
        "company":    cv_meta.get("target_company", ""),
        "platform":   payload.meta.get("platform", ""),
        "job_url":    payload.meta.get("source_url", ""),
        "cv_file":    output_file,
        "cv_path":    output_path,
        "status":     "cv_generated",
        "notes":      "",
        "created_at": datetime.now().isoformat(),
    }
    _append_suivi(suivi_entry)
    append_application(suivi_entry)   # no-op if google_credentials.json absent

    return {
        "success":    True,
        "filename":   output_file,
        "path":       output_path,
        "role":       cv_meta.get("target_role", ""),
        "company":    cv_meta.get("target_company", ""),
        "suivi_id":   suivi_entry["id"],
        "dashboard":  "http://localhost:8000",
    }


def _render_letter_pdf(text: str, out_path: str, candidate_name: str,
                       identity: dict = None, company: str = "", role: str = ""):
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.colors import black, HexColor

    fonts_dir = str(BASE_DIR / "fonts")
    try:
        pdfmetrics.registerFont(TTFont("OpenSans", f"{fonts_dir}/OpenSans-Regular.ttf"))
        pdfmetrics.registerFont(TTFont("OpenSans-Bold", f"{fonts_dir}/OpenSans-Bold.ttf"))
        body_font, title_font = "OpenSans", "OpenSans-Bold"
    except Exception:
        body_font, title_font = "Helvetica", "Helvetica-Bold"

    W, H = A4
    margin_x, margin_top, margin_bottom = 72, 72, 60
    max_w = W - 2 * margin_x
    line_h = 14

    c = rl_canvas.Canvas(out_path, pagesize=A4)
    title_parts = [candidate_name]
    if company:
        title_parts.append(company)
    c.setTitle(f"Lettre de motivation — {' · '.join(title_parts)}")

    def new_page():
        c.showPage()
        return H - margin_top

    y = H - margin_top

    # ── Classic French letter header ─────────────────────────────────────────
    if identity:
        id_ = identity
        # Sender block (top-left)
        c.setFont(title_font, 11)
        c.setFillColor(black)
        c.drawString(margin_x, y, id_.get("full_name", ""))
        y -= 14
        c.setFont(body_font, 9.5)
        c.setFillColor(HexColor("#444444"))
        sender_lines = [
            id_.get("title", ""),
            id_.get("address", ""),
            id_.get("phone", ""),
            id_.get("email", ""),
        ]
        for line in sender_lines:
            if line:
                c.drawString(margin_x, y, line)
                y -= 12
        y -= 10

        # Date (right-aligned)
        today_str = date.today().strftime("%d/%m/%Y")
        c.setFont(body_font, 9.5)
        date_w = c.stringWidth(f"Paris, le {today_str}", body_font, 9.5)
        c.drawString(W - margin_x - date_w, y, f"Paris, le {today_str}")
        y -= 24

        # Separator line
        c.setStrokeColor(HexColor("#CCCCCC"))
        c.setLineWidth(0.5)
        c.line(margin_x, y, W - margin_x, y)
        y -= 16
        c.setFillColor(black)

        # Objet line
        if company or role:
            objet_parts = []
            if role:
                objet_parts.append(role)
            if company:
                objet_parts.append(f"chez {company}")
            objet_value = " ".join(objet_parts)
            objet_label = "Objet : "
            lw = c.stringWidth(objet_label, title_font, 10)
            c.setFont(title_font, 10)
            c.drawString(margin_x, y, objet_label)
            c.setFont(body_font, 10)
            c.drawString(margin_x + lw, y, f"Candidature au poste de {objet_value}")
            y -= 20

    for paragraph in text.split("\n"):
        # Word-wrap each paragraph
        words = paragraph.split()
        if not words:
            y -= line_h * 0.6
            if y < margin_bottom:
                y = new_page()
            continue

        c.setFont(body_font, 10.5)
        c.setFillColor(black)
        line, lines = "", []
        for word in words:
            candidate_line = (line + " " + word).strip()
            if c.stringWidth(candidate_line, body_font, 10.5) <= max_w:
                line = candidate_line
            else:
                lines.append(line)
                line = word
        lines.append(line)

        for ln in lines:
            if y < margin_bottom:
                y = new_page()
                c.setFont(body_font, 10.5)
            c.drawString(margin_x, y, ln)
            y -= line_h
        y -= line_h * 0.3  # paragraph spacing

    c.save()


@app.post("/generate-letter")
async def generate_letter(payload: JobPayload):
    if not MASTER_FILE.exists():
        raise HTTPException(500, "cv_master_profile.json introuvable")

    with open(MASTER_FILE, encoding="utf-8") as f:
        master = json.load(f)

    cv_root  = master
    job_desc = payload.job.get("description", "") or payload.for_ai.get("prompt_ready", "")

    if not job_desc:
        raise HTTPException(400, "Description du poste vide")

    filtered = _filter_profile(cv_root, job_desc)

    # Identity comes from cv_main.json (master profile has none)
    with open(SOC_CV_FILE, encoding="utf-8") as f:
        identity = json.load(f).get("identity", {})
    candidate_name = identity.get("full_name", "Khalil Ghiati")

    prompt = LETTER_PROMPT_TEMPLATE.format(
        job_description  = job_desc,
        master_profile   = json.dumps(filtered, ensure_ascii=False, separators=(",", ":")),
        candidate_name   = candidate_name,
    )

    client = Groq(api_key=os.getenv("Groq_API_text_analysis"))
    response = client.chat.completions.create(
        model           = "meta-llama/llama-4-scout-17b-16e-instruct",
        messages        = [{"role": "user", "content": prompt}],
        max_tokens      = 1200,
        temperature     = 0.55,
        response_format = {"type": "json_object"},
    )

    raw = json.loads(response.choices[0].message.content)
    letter_text  = raw.get("letter", "").strip()
    company_name = raw.get("company", "").strip()
    role_name    = raw.get("role", "").strip()

    # Save to lettres/ folder
    today     = date.today().strftime("%Y-%m-%d")
    safe_co   = re.sub(r'[^\w\s-]', '', company_name or job_desc[:40]).strip().replace(" ", "_")[:30]
    filename  = f"LM_{safe_co}_{today}.pdf"
    out_path  = LETTRES_DIR / filename

    _render_letter_pdf(letter_text, str(out_path), candidate_name,
                       identity=identity, company=company_name, role=role_name)

    return {
        "success":  True,
        "filename": filename,
        "path":     str(out_path),
        "company":  company_name,
        "role":     role_name,
        "preview":  letter_text[:300] + ("…" if len(letter_text) > 300 else ""),
    }
