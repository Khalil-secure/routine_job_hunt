import json, re
from ats_optimizer import score_ats, SAMPLE_JOB

with open("_last_generated_cv.json", encoding="utf-8") as f:
    cv = json.load(f)

# Generated CV uses flat skills list — wrap it into the dict format score_ats expects
if isinstance(cv.get("skills"), list):
    cv["skills"] = {
        "tech": {"items": [{"skill": s["label"]} for s in cv["skills"]]}
    }

r = score_ats(cv, SAMPLE_JOB)
print("TOTAL:", r["total"], "%\n")
for k, v in r["scores"].items():
    bar = "#" * round(v/100*28) + "." * (28 - round(v/100*28))
    print(f"  {k:<14} [{bar}] {v}%")
if r["gaps"]:
    print("\nGAPS:")
    for g in r["gaps"]:
        print(" !!", g)
