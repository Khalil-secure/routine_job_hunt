"""Quick test — sends a fake job offer to Groq, prints the CV JSON result."""
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

MASTER_FILE = Path(__file__).parent / "cv_master_profile.json"

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


from backend import _filter_profile, PROMPT_TEMPLATE


def main():
    print("📂  Loading master profile...")
    with open(MASTER_FILE, encoding="utf-8") as f:
        master = json.load(f)

    cv_root  = master.get("cv", master)
    filtered = _filter_profile(cv_root, SAMPLE_JOB)

    profile_json = json.dumps(filtered, ensure_ascii=False, separators=(",", ":"))
    print(f"📐  Profile tokens (chars/4): ~{len(profile_json)//4}")

    prompt = PROMPT_TEMPLATE.format(
        job_description = SAMPLE_JOB,
        master_profile  = profile_json,
    )

    print("🤖  Calling Groq (llama-3.3-70b-versatile)...")
    client = Groq(api_key=os.getenv("Groq_API_text_analysis"))
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=4096,
        temperature=0.4,
    )

    raw     = response.choices[0].message.content
    cv_json = json.loads(raw)
    cv      = cv_json.get("cv", cv_json)

    # ── Pretty print key sections ──────────────────────────────────────────────
    print("\n" + "═"*60)
    print(f"  TARGET ROLE    : {cv.get('meta', {}).get('target_role', '?')}")
    print(f"  TARGET COMPANY : {cv.get('meta', {}).get('target_company', '?')}")
    print("═"*60)

    print("\n📝  PROFILE SUMMARY:")
    print(cv.get("profile", {}).get("summary_fr", "—"))

    print("\n💼  EXPERIENCES SELECTED:")
    for e in cv.get("experience", []):
        print(f"  • {e.get('company')} — {e.get('role')}")
        for m in e.get("missions", [])[:2]:
            desc = m if isinstance(m, str) else m.get("description", "")
            print(f"      - {desc[:120]}{'…' if len(desc)>120 else ''}")

    print("\n🎓  EDUCATION:")
    for edu in cv.get("education", []):
        print(f"  • {edu.get('institution')} — {edu.get('degree')}")

    print("\n🏅  CERTIFICATIONS:")
    for c in cv.get("certifications", []):
        print(f"  • {c.get('name')} ({c.get('issuer')})")

    print("\n🚀  PROJECTS:")
    for p in cv.get("projects", []):
        print(f"  • {p.get('name')} [{', '.join(p.get('tech', [])[:4])}]")

    # Word count check
    all_text = json.dumps(cv, ensure_ascii=False)
    words    = len(all_text.split())
    print(f"\n📊  Total words in JSON: {words}")
    print(f"    Tokens used: {response.usage.total_tokens}")

    # Save full output for inspection
    out = Path(__file__).parent / "_test_cv_output.json"
    out.write_text(json.dumps(cv_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅  Full JSON saved → {out}")

    # Try to generate the docx too
    print("\n🏗️  Testing docx generation...")
    try:
        from cv_from_json import generate_cv as build_docx
        import re
        from datetime import date
        role    = re.sub(r'[^\w\s-]', '', cv.get("meta", {}).get("target_role", "role")).strip().replace(" ", "_")[:40]
        company = re.sub(r'[^\w\s-]', '', cv.get("meta", {}).get("target_company", "company")).strip().replace(" ", "_")[:30]
        docx_out = Path(__file__).parent / "CV_jobs" / f"{role}_{company}_{date.today()}.docx"
        build_docx(str(out), str(docx_out))
        print(f"✅  DOCX saved → {docx_out}")
    except Exception as ex:
        print(f"⚠️  DOCX generation failed: {ex}")


if __name__ == "__main__":
    main()
