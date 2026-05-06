"""
ats_optimizer.py — ATS loop optimizer for French job market
Generates CV + lettre de motivation, scores with French ATS criteria,
optimises the prompt iteratively until >= 90% ATS score.
"""

import json, os, re, sys
from pathlib import Path
from datetime import date
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))
from backend import _filter_profile

MASTER_FILE = Path(__file__).parent / "cv_master_profile.json"
OUT_DIR     = Path(__file__).parent / "ats_runs"
OUT_DIR.mkdir(exist_ok=True)

SAMPLE_JOB = """
Analyste SOC N1/N2 — CDD 12 mois — Lyon

Rejoignez notre équipe Blue Team au sein d'un SOC mutualisé.

Missions :
- Surveillance et analyse des alertes SIEM (Splunk, Microsoft Sentinel)
- Qualification et triage des incidents de sécurité (Tier 1 & Tier 2)
- Investigation forensique basique : analyse de logs, flux réseau (Wireshark, Zeek)
- Application du framework MITRE ATT&CK pour le mapping des TTPs
- Rédaction de rapports d'incidents et de fiches de remédiation
- Participation aux runbooks de réponse aux incidents (SOAR)
- Veille sur les CVE critiques et IOCs (VirusTotal, MISP)

Profil recherché :
- Bac+4/Bac+5 en informatique, réseau ou cybersécurité
- Connaissance des protocoles réseau (TCP/IP, DNS, HTTP, TLS)
- Expérience ou formation sur un SIEM (Splunk ou ELK obligatoire)
- Certifications appréciées : SOC Level 1, CompTIA Security+, CEH
- Maîtrise de Linux et scripting Bash/Python
- ISO 27001 est un plus
- Anglais technique lu/écrit

Entreprise : SecureOps Lyon
"""

# -- ATS Scoring ----------------------------------------------------------------

HARD_KW_PATTERNS = [
    r"splunk", r"microsoft sentinel", r"sentinel", r"elastic", r"elk", r"qradar", r"siem",
    r"mitre att&?ck", r"mitre", r"att&ck", r"soar",
    r"wireshark", r"zeek", r"virustotal", r"misp",
    r"soc level 1", r"comptia security\+", r"security\+", r"ceh",
    r"iso 27001", r"iso/iec 27001",
    r"tcp/ip", r"dns", r"http", r"tls",
    r"python", r"bash", r"scripting", r"linux",
    r"forensi", r"triage", r"runbook", r"réponse aux incidents",
    r"ioc", r"cve", r"ttp",
    r"blue team", r"analyste soc", r"tier 1", r"tier 2", r"qualification",
    r"rapport d.incident", r"remédiation",
]

ACTION_VERBS = [
    "déployé", "configuré", "automatisé", "analysé", "supervisé",
    "migré", "réduit", "optimisé", "développé", "implémenté",
    "intégré", "sécurisé", "audité", "détecté", "investigué",
    "coordonné", "livré", "rédigé", "mis en place",
]

REQUIRED_SKILLS = [
    "splunk", "siem", "mitre", "python", "linux", "tcp",
    "wireshark", "iso 27001", "soc", "bash",
]

QUANT_RE = re.compile(
    r'\d+%|\d+ %|\d+\+|x\d+|\d+ sites|\d+ projets|\d+ endpoint|\d+ serveur|'
    r'réduit|automatisé|éliminé|doublé|zéro|100%|mttr|sans interruption|'
    r'\d+ mois|\d+ clients|\d+ alertes',
    re.IGNORECASE
)


def score_ats(cv: dict, job_desc: str) -> dict:
    blob = json.dumps(cv, ensure_ascii=False).lower()

    # 1. Keyword coverage (35%)
    found_kw   = [p for p in HARD_KW_PATTERNS if re.search(p, blob)]
    kw_score   = round(len(found_kw) / len(HARD_KW_PATTERNS) * 100)
    missing_kw = [p for p in HARD_KW_PATTERNS if p not in found_kw]

    # 2. Section completeness (15%)
    sections = {
        "accroche":       bool(cv.get("profile", {}).get("summary_fr", "").strip()),
        "expériences":    len(cv.get("experience", [])) >= 1,
        "formation":      len(cv.get("education", [])) >= 1,
        "compétences":    bool(cv.get("skills")),
        "certifications": len(cv.get("certifications", [])) >= 1,
        "projets":        len(cv.get("projects", [])) >= 1,
        "langues":        len(cv.get("languages", [])) >= 1,
    }
    section_score    = round(sum(sections.values()) / len(sections) * 100)
    missing_sections = [s for s, ok in sections.items() if not ok]

    # 3. Quantified bullets (15%)
    bullets = []
    for exp in cv.get("experience", []):
        for m in exp.get("missions", []):
            bullets.append(m if isinstance(m, str) else m.get("description", ""))
    quant_bullets = [b for b in bullets if QUANT_RE.search(b)]
    quant_score   = min(100, round(len(quant_bullets) / max(len(bullets), 1) * 100 * 1.4))

    # 4. Title alignment (10%)
    target_role  = cv.get("meta", {}).get("target_role", "").lower()
    title_words  = {"analyste", "soc", "n1", "n2"}
    role_words   = set(re.findall(r"\w+", target_role))
    title_score  = round(len(title_words & role_words) / len(title_words) * 100)

    # 5. Action verbs (10%)
    found_verbs = [v for v in ACTION_VERBS if v in blob]
    verb_score  = min(100, round(len(found_verbs) / 8 * 100))

    # 6. Skills completeness (15%)
    skill_items = []
    for cat in cv.get("skills", {}).values():
        if isinstance(cat, dict):
            for item in cat.get("items", []):
                val = item.get("skill", item.get("language", "")) if isinstance(item, dict) else str(item)
                skill_items.append(val.lower())
    skill_blob    = " ".join(skill_items)
    found_skills  = [s for s in REQUIRED_SKILLS if s in skill_blob or s in blob]
    skills_score  = round(len(found_skills) / len(REQUIRED_SKILLS) * 100)
    missing_skills = [s for s in REQUIRED_SKILLS if s not in found_skills]

    weights = {"keywords": 0.35, "sections": 0.15, "quantified": 0.15,
               "title": 0.10, "verbs": 0.10, "skills": 0.15}
    raw     = {"keywords": kw_score, "sections": section_score, "quantified": quant_score,
               "title": title_score, "verbs": verb_score, "skills": skills_score}
    total   = round(sum(raw[k] * w for k, w in weights.items()))

    gaps = []
    if missing_kw:
        gaps.append(f"MOTS-CLÉS MANQUANTS ({len(missing_kw)}): {', '.join(missing_kw[:10])}")
    if missing_sections:
        gaps.append(f"SECTIONS MANQUANTES: {', '.join(missing_sections)}")
    if quant_score < 70:
        n_missing = len(bullets) - len(quant_bullets)
        gaps.append(f"BULLETS SANS CHIFFRE: {n_missing}/{len(bullets)} bullets non quantifiés")
    if missing_skills:
        gaps.append(f"SKILLS ABSENTS: {', '.join(missing_skills)}")
    if title_score < 75:
        gaps.append(f"TITRE NON ALIGNÉ: '{cv.get('meta',{}).get('target_role','')}' — attendu 'Analyste SOC N1/N2'")

    return {"total": total, "scores": raw, "gaps": gaps,
            "detail": {"kw_found": found_kw, "kw_missing": missing_kw,
                       "bullets": len(bullets), "bullets_quant": len(quant_bullets),
                       "verbs": found_verbs, "skills_missing": missing_skills}}


def score_letter(letter: str) -> dict:
    text = letter.lower()
    kw_found     = [p for p in HARD_KW_PATTERNS if re.search(p, text)]
    kw_score     = round(len(kw_found) / len(HARD_KW_PATTERNS) * 100)
    has_greeting = "madame, monsieur" in text
    has_closing  = "cordialement" in text
    has_cta      = "entretien" in text
    paragraphs   = [p for p in letter.split("\n\n") if len(p.strip()) > 40]
    struct_score = round((has_greeting + has_closing + has_cta + (len(paragraphs) >= 3)) / 4 * 100)
    concrete     = len(re.findall(r'\d+%|\d+\+|\d+ sites|\d+ endpoints|splunk|mitre|siem|iso 27001|soc level|wireshark', text))
    concrete_score = min(100, concrete * 14)
    words        = len(letter.split())
    length_score = 100 if 260 <= words <= 340 else 75 if 220 <= words <= 380 else 50
    total        = round(kw_score * 0.30 + struct_score * 0.25 + concrete_score * 0.25 + length_score * 0.20)
    gaps = []
    if kw_score < 60:
        missing = [p for p in HARD_KW_PATTERNS if not re.search(p, text)]
        gaps.append(f"Mots-clés manquants: {', '.join(missing[:6])}")
    if not has_cta:
        gaps.append("Appel à l'action 'entretien' manquant")
    if concrete_score < 60:
        gaps.append("Trop peu de chiffres/outils — ajouter des réalisations concrètes")
    if words < 260:
        gaps.append(f"Trop court ({words} mots) — objectif 280-320")
    return {"total": total, "words": words, "kw": kw_score,
            "struct": struct_score, "concrete": concrete_score, "gaps": gaps}


# -- Prompts --------------------------------------------------------------------

def build_cv_prompt(profile_json: str, fix_block: str) -> str:
    return f"""\
Tu es un expert ATS et recrutement tech France. Mission : générer un CV JSON qui passe les ATS à 90%+ ET impressionne le recruteur humain en racontant une histoire cohérente.

=== OFFRE D'EMPLOI ===
{SAMPLE_JOB}

=== PROFIL CANDIDAT ===
{profile_json}

{fix_block}
=== MISSION ===
Génère un CV JSON ultra-ciblé. UNIQUEMENT du JSON valide.

SCHÉMA :
{{
  "cv": {{
    "meta": {{"target_role":"Analyste SOC N1/N2","target_company":"SecureOps Lyon"}},
    "identity": {{...copier depuis le profil...}},
    "profile": {{"summary_fr":"<3 phrases 65-80 mots>"}},
    "experience": [...],
    "education": [...],
    "skills": {{...}},
    "certifications": [...],
    "projects": [...3 max...],
    "languages": [...]
  }}
}}

--- RÈGLES ATS FRANCE — NON NÉGOCIABLES ---

ACCROCHE (summary_fr) — 3 phrases, 65-80 mots TOTAL :
• P1 : "Analyste SOC N1/N2" + diplôme ingénieur Bac+5 (ENSIL-ENSCI) + spécialisation
• P2 : réalisation concrète avec CHIFFRE liée à surveillance/sécurité/infra (ex: 1200 endpoints, 300 sites)
• P3 : certifications SOC Level 1 + ISO 27001 + motivation pour Blue Team SecureOps
→ Mots-clés OBLIGATOIRES dans l'accroche : SIEM, MITRE ATT&CK, Blue Team, incidents, Splunk
→ INTERDIT : "passionné", "dynamique", "motivé", "je suis"

EXPÉRIENCES — anti-chronologique, EXACTEMENT 3 bullets par poste :
• Format : [Contexte opérationnel + outil] → [Action précise] → [Résultat chiffré]
• Chaque bullet DOIT avoir au moins 1 mot-clé de l'offre ET 1 chiffre ou qualificatif fort
• Exemples de résultats acceptables : "MTTR réduit de 35%", "1200 endpoints supervisés", "zéro interruption de service", "300 sites couverts", "90% de gain en efficacité"
• missions = liste de STRINGS uniquement

SKILLS — 6 catégories OBLIGATOIRES :
security_soc, network_cloud, devops_automation, programming, web_infrastructure, methodology
• security_soc EN TÊTE : Splunk, Microsoft Sentinel, MITRE ATT&CK, Wireshark, SIEM, IDS/IPS, SOAR, VirusTotal, MISP
• methodology EN TÊTE : ISO 27001, MITRE ATT&CK, Runbooks, ANSSI, CIS Benchmark

PROJETS — 3 max, miroir de l'offre (SOC, détection, logs, Python, sécurité réseau) :
• Chaque projet : name + tech (liste) + 1 ligne description avec impact

CERTIFICATIONS : SOC Level 1 EN PREMIER, puis ISO/IEC 27001 — dates EXACTES du profil

GÉNÉRAL :
• 550+ mots dans les champs texte
• Ne jamais inventer — tout vient du profil
• Dates : recopier EXACTEMENT depuis le profil
"""


def build_fix_block(iteration: int, score: int, gaps: list, scores: dict) -> str:
    if not gaps:
        return ""
    fixes = []
    for gap in gaps:
        if "MOTS-CLÉS MANQUANTS" in gap:
            missing = re.findall(r":\s*(.+)", gap)[0]
            fixes.append(f"• Intégrer ces termes manquants dans accroche + bullets + skills : {missing}")
        if "BULLETS SANS CHIFFRE" in gap:
            fixes.append(
                "• Réécrire les bullets sans chiffre — utiliser les achievements du profil : "
                "1200 endpoints, 300 sites, 90% efficacité, 4 projets 5G/LTE/FTTH, "
                "migration VMware→Hyper-V zéro interruption, CIS Benchmark Level 2"
            )
        if "SKILLS ABSENTS" in gap:
            missing = re.findall(r":\s*(.+)", gap)[0]
            fixes.append(f"• Ajouter IMPÉRATIVEMENT dans skills.security_soc ou network_cloud : {missing}")
        if "TITRE NON ALIGNÉ" in gap:
            fixes.append('• meta.target_role = "Analyste SOC N1/N2" — exactement, sans variation')
    if scores.get("verbs", 100) < 70:
        fixes.append(
            "• Commencer chaque bullet par un verbe fort au passé : déployé, automatisé, "
            "analysé, supervisé, migré, sécurisé, investigué, rédigé"
        )
    lines = "\n".join(fixes)
    return f"""
=== CORRECTIONS OBLIGATOIRES ITÉRATION {iteration} (score actuel {score}% → objectif 90%) ===
{lines}

"""


LETTER_PROMPT_TPL = """\
Tu rédiges une lettre de motivation en français pour Khalil Ghiati. Directe, authentique, sans langue de bois.

=== OFFRE ===
{job}

=== PROFIL ===
{profile}

=== RÈGLES ===

STRUCTURE — 3 paragraphes, 285-315 mots TOTAL :

§1 ACCROCHE (5 lignes) :
• Ouvrir sur le défi de SecureOps Lyon — SOC mutualisé, volume d'alertes à qualifier 24/7
• Montrer que tu as lu l'offre : nommer Splunk ou MITRE ATT&CK ou triage Tier 1/2
• Ne PAS commencer par "Je me permets..."
• Commencer par une observation sur l'environnement SOC, pas sur toi

§2 VALEUR AJOUTÉE (8 lignes) :
• Réalisation 1 liée à une mission de l'offre + chiffre (1200 endpoints, 300 sites, 90% gains)
• Réalisation 2 : certification ou formation prouvée (SOC Level 1 TryHackMe, ISO 27001, MITRE ATT&CK)
• Réalisation 3 : projet ou compétence scripting/détection (Python, Bash, logs, forensique)
• Intégrer naturellement : SIEM, Blue Team, triage, incidents, runbooks, IOC

§3 ADÉQUATION + APPEL À L'ACTION (5 lignes) :
• Ce que CE poste t'apporte précisément (terrain Blue Team réel, diversité multi-clients SOC mutualisé)
• Motivation pour Lyon, cet environnement, cette structure
• Clôture assertive, confiante — pas obséquieuse

FORMAT :
- Commencer par : "Madame, Monsieur,"
- Terminer par : "Dans l'attente de votre retour, je reste disponible pour un entretien.\\n\\nCordialement,\\nKhalil Ghiati"
- Ton : professionnel, direct, humain
- NE PAS inventer — tout vient du profil
- Aucun JSON, aucun titre, aucun commentaire extra

Réponds UNIQUEMENT avec le texte de la lettre.
"""


# -- Display helpers ------------------------------------------------------------

def bar(label: str, score: int, w: int = 28):
    filled = round(score / 100 * w)
    b      = "#" * filled + "." * (w - filled)
    c = "\033[92m" if score >= 90 else "\033[93m" if score >= 70 else "\033[91m"
    print(f"  {label:<16} {c}{b}\033[0m {score:3d}%")


# -- Main -----------------------------------------------------------------------

def main():
    print("\n" + "="*62)
    print("  ATS OPTIMIZER — Marché français  |  Objectif : ≥ 90%")
    print("="*62)

    with open(MASTER_FILE, encoding="utf-8") as f:
        master = json.load(f)

    cv_root      = master.get("cv", master)
    filtered     = _filter_profile(cv_root, SAMPLE_JOB)
    profile_json = json.dumps(filtered, ensure_ascii=False, separators=(",", ":"))

    client     = Groq(api_key=os.getenv("Groq_API_text_analysis"))
    best_cv    = None
    best_score = 0
    best_result= None
    MAX_ITER   = 6
    fix_block  = ""

    for iteration in range(1, MAX_ITER + 1):
        print(f"\n{'-'*62}")
        print(f"  ITÉRATION {iteration}/{MAX_ITER}")
        print(f"{'-'*62}")

        prompt = build_cv_prompt(profile_json, fix_block)
        print("  → Groq llama-3.3-70b-versatile...")

        resp    = client.chat.completions.create(
            model           = "llama-3.3-70b-versatile",
            messages        = [{"role": "user", "content": prompt}],
            response_format = {"type": "json_object"},
            max_tokens      = 4096,
            temperature     = 0.25,
        )
        raw     = resp.choices[0].message.content
        cv_json = json.loads(raw)
        cv      = cv_json.get("cv", cv_json)

        result = score_ats(cv, SAMPLE_JOB)
        total  = result["total"]
        scores = result["scores"]
        gaps   = result["gaps"]

        print(f"\n  ATS SCORE : {total}%\n")
        bar("Keywords   (35%)", scores["keywords"])
        bar("Sections   (15%)", scores["sections"])
        bar("Quantified (15%)", scores["quantified"])
        bar("Title      (10%)", scores["title"])
        bar("Verbs      (10%)", scores["verbs"])
        bar("Skills     (15%)", scores["skills"])
        print(f"  {'-'*44}")
        bar("TOTAL ATS      ", total)

        if gaps:
            print("\n  GAPS :")
            for g in gaps:
                print(f"    [!!]  {g}")

        # Save iteration
        out = OUT_DIR / f"iter{iteration}_score{total}.json"
        out.write_text(
            json.dumps({"iteration": iteration, "score": total, "scores": scores,
                        "gaps": gaps, "cv": cv}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"  → {out.name}")

        if total > best_score:
            best_score  = total
            best_cv     = cv
            best_result = result

        if total >= 90:
            print(f"\n  [OK]  OBJECTIF ATTEINT — {total}%")
            break

        fix_block = build_fix_block(iteration, total, gaps, scores)

    # -- Cover letter ----------------------------------------------------------
    print(f"\n{'='*62}")
    print("  LETTRE DE MOTIVATION")
    print(f"{'='*62}")

    letter_prompt = LETTER_PROMPT_TPL.format(job=SAMPLE_JOB, profile=profile_json)
    lr = client.chat.completions.create(
        model       = "llama-3.3-70b-versatile",
        messages    = [{"role": "user", "content": letter_prompt}],
        max_tokens  = 1200,
        temperature = 0.55,
    )
    letter       = lr.choices[0].message.content.strip()
    lscore       = score_letter(letter)

    print(f"\n  Lettre : {lscore['words']} mots\n")
    bar("Mots-clés  (30%)", lscore["kw"])
    bar("Structure  (25%)", lscore["struct"])
    bar("Concret    (25%)", lscore["concrete"])
    bar("Longueur   (20%)", lscore["length"])
    print(f"  {'-'*44}")
    bar("SCORE LETTRE   ", lscore["total"])

    if lscore["gaps"]:
        print("\n  GAPS LETTRE :")
        for g in lscore["gaps"]:
            print(f"    [!!]  {g}")

    lf = OUT_DIR / f"lettre_{date.today()}.txt"
    lf.write_text(letter, encoding="utf-8")
    print(f"  → {lf}")

    # Save best CV
    bf = OUT_DIR / f"best_cv_score{best_score}_{date.today()}.json"
    bf.write_text(
        json.dumps({"score": best_score, "ats": best_result, "cv": best_cv},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # -- Summary ---------------------------------------------------------------
    print(f"\n{'='*62}")
    print(f"  RÉSULTAT FINAL")
    print(f"  Meilleur score ATS CV  : {best_score}%  {'[OK]' if best_score >= 90 else '[!!]  < 90%'}")
    print(f"  Score lettre           : {lscore['total']}%")
    print(f"  Itérations             : {iteration}")
    print(f"  Outputs                : {OUT_DIR}")
    if best_score < 90:
        print(f"\n  Gaps restants :")
        for g in (best_result or {}).get("gaps", []):
            print(f"    → {g}")
    print(f"{'='*62}")

    print(f"\n{'='*62}")
    print("  LETTRE DE MOTIVATION")
    print(f"{'='*62}")
    print(letter)
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
