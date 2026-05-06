"""
setup_sheets.py — one-time Google Sheets connection test

Run this after placing google_credentials.json in the project folder.

Steps to get google_credentials.json:
  1. Go to https://console.cloud.google.com  →  create a project (or pick one)
  2. APIs & Services  →  Enable APIs  →  search "Google Sheets API"  →  Enable
  3. IAM & Admin  →  Service Accounts  →  Create service account
     (name it anything, e.g. "cv-tracker")
  4. Click the account  →  Keys tab  →  Add Key  →  JSON  →  download
  5. Rename the file to  google_credentials.json  and put it here:
       D:/code/cyberdeck/routine_job_hunt/google_credentials.json
  6. Run this script — it will print the service-account email
  7. Open your Google Sheet  →  Share  →  paste that email  →  Editor
  8. Run this script again to confirm the connection

Usage:
    python setup_sheets.py
"""

import sys, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR   = Path(__file__).parent
CREDS_FILE = BASE_DIR / "google_credentials.json"

def main():
    # ── Step 1: check credentials file ────────────────────────────────────────
    if not CREDS_FILE.exists():
        print("❌  google_credentials.json not found.")
        print(f"    Expected path: {CREDS_FILE}")
        print("\n    Follow the steps at the top of this file to create it.")
        sys.exit(1)

    with open(CREDS_FILE, encoding="utf-8") as f:
        creds_data = json.load(f)

    sa_email = creds_data.get("client_email", "unknown")
    print(f"✅  Credentials loaded.")
    print(f"    Service account: {sa_email}")
    print(f"\n    >>> Share your Google Sheet with this email (Editor access) <<<\n")

    # ── Step 2: try to import gspread ─────────────────────────────────────────
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("❌  gspread not installed. Run:  pip install gspread google-auth")
        sys.exit(1)

    # ── Step 3: connect to the sheet ──────────────────────────────────────────
    import os
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if not sheet_id:
        print("❌  GOOGLE_SHEET_ID not found in .env")
        sys.exit(1)

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]

    try:
        creds  = Credentials.from_service_account_file(str(CREDS_FILE), scopes=SCOPES)
        client = gspread.authorize(creds)
        book   = client.open_by_key(sheet_id)
        print(f"✅  Connected to spreadsheet: \"{book.title}\"")
    except gspread.exceptions.APIError as e:
        if "403" in str(e):
            print("❌  Permission denied (403).")
            print(f"    Make sure you shared the sheet with:  {sa_email}")
        else:
            print(f"❌  API error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌  Connection failed: {e}")
        sys.exit(1)

    # ── Step 4: init/verify the Suivi tab ─────────────────────────────────────
    HEADERS  = ["Date", "Poste", "Entreprise", "Plateforme",
                "URL Offre", "Fichier CV", "Statut", "Notes", "ID"]
    TAB_NAME = "Suivi"

    try:
        sheet = book.worksheet(TAB_NAME)
        print(f"✅  Tab \"{TAB_NAME}\" found  ({sheet.row_count} rows)")
    except gspread.WorksheetNotFound:
        sheet = book.add_worksheet(title=TAB_NAME, rows=1000, cols=len(HEADERS))
        sheet.append_row(HEADERS, value_input_option="RAW")
        sheet.format("A1:I1", {
            "textFormat":          {"bold": True, "foregroundColor": {"red":1,"green":1,"blue":1}},
            "backgroundColor":     {"red": 0.10, "green": 0.45, "blue": 0.91},
            "horizontalAlignment": "CENTER",
        })
        print(f"✅  Tab \"{TAB_NAME}\" created with headers")

    # ── Step 5: write + delete a test row ─────────────────────────────────────
    test_row = ["2026-01-01", "TEST ROLE", "TEST CO", "test",
                "http://test", "test.docx", "📄 CV généré", "", "test-id"]
    sheet.append_row(test_row, value_input_option="RAW")

    # find and delete it
    ids = sheet.col_values(9)
    try:
        row_num = ids.index("test-id") + 1
        sheet.delete_rows(row_num)
        print("✅  Test row written and deleted — sheet is writable")
    except ValueError:
        print("⚠️  Could not clean up test row — check the sheet manually")

    print("\n🎉  All good! Google Sheets integration is ready.")
    print("    Every CV you generate will now appear in the sheet automatically.")

if __name__ == "__main__":
    main()
