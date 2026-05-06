"""
sheets.py — Google Sheets sync for suivi
Appends a row on every CV generation, updates status on PATCH.

Setup (one time):
  1. Go to console.cloud.google.com → New project
  2. Enable "Google Sheets API"
  3. IAM & Admin → Service Accounts → Create → download JSON key
  4. Save the JSON as  google_credentials.json  in this folder
  5. Share your spreadsheet with the service-account email (Editor)
  6. Add to .env:  GOOGLE_SHEET_ID=1LSwCEk1fUVu_X0t3A58PcwLVgWfR2HedV9-EjEtj2XU
"""

import os, json
from pathlib import Path
from datetime import datetime

try:
    import gspread
    from google.oauth2.service_account import Credentials
    _GSPREAD_AVAILABLE = True
except ImportError:
    _GSPREAD_AVAILABLE = False

BASE_DIR      = Path(__file__).parent
CREDS_FILE    = BASE_DIR / "google_credentials.json"
SHEET_ID      = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_TAB     = "Suivi"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

HEADERS = ["Date", "Poste", "Entreprise", "Plateforme",
           "URL Offre", "Fichier CV", "Statut", "Notes", "ID"]

STATUS_LABELS = {
    "cv_generated": "📄 CV généré",
    "applied":      "📤 Postulé",
    "interview":    "🎯 Entretien",
    "offer":        "🎉 Offre",
    "rejected":     "❌ Refusé",
    "ghosted":      "👻 Ghosté",
}


def _get_sheet():
    if not _GSPREAD_AVAILABLE:
        raise RuntimeError("gspread not installed — run: pip install gspread google-auth")
    if not CREDS_FILE.exists():
        raise RuntimeError(f"google_credentials.json not found in {BASE_DIR}")
    if not SHEET_ID:
        raise RuntimeError("GOOGLE_SHEET_ID missing from .env")

    creds  = Credentials.from_service_account_file(str(CREDS_FILE), scopes=SCOPES)
    client = gspread.authorize(creds)
    book   = client.open_by_key(SHEET_ID)

    # Get or create the tab
    try:
        sheet = book.worksheet(SHEET_TAB)
    except gspread.WorksheetNotFound:
        sheet = book.add_worksheet(title=SHEET_TAB, rows=1000, cols=len(HEADERS))
        sheet.append_row(HEADERS, value_input_option="RAW")
        _format_header(sheet)

    # Auto-create headers if the sheet is empty
    if sheet.row_count == 0 or not sheet.row_values(1):
        sheet.append_row(HEADERS, value_input_option="RAW")
        _format_header(sheet)

    return sheet


def _format_header(sheet):
    """Bold + blue background on the header row."""
    try:
        sheet.format("A1:I1", {
            "textFormat":        {"bold": True, "foregroundColor": {"red":1,"green":1,"blue":1}},
            "backgroundColor":   {"red": 0.10, "green": 0.45, "blue": 0.91},
            "horizontalAlignment": "CENTER",
        })
    except Exception:
        pass


def append_application(entry: dict) -> bool:
    """Append one row. Returns True on success, False if sheets not configured."""
    try:
        sheet = _get_sheet()
        row = [
            entry.get("date", ""),
            entry.get("role", ""),
            entry.get("company", ""),
            entry.get("platform", ""),
            entry.get("job_url", ""),
            entry.get("cv_file", ""),
            STATUS_LABELS.get(entry.get("status", ""), entry.get("status", "")),
            entry.get("notes", ""),
            entry.get("id", ""),
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        return True
    except RuntimeError as e:
        print(f"[sheets] Skipped (not configured): {e}")
        return False
    except Exception as e:
        print(f"[sheets] Error appending row: {e}")
        return False


def update_status(entry_id: str, status: str, notes: str = "") -> bool:
    """Find the row by ID (col I) and update Statut + Notes columns."""
    try:
        sheet  = _get_sheet()
        ids    = sheet.col_values(9)       # column I = ID
        try:
            row_num = ids.index(entry_id) + 1  # 1-indexed
        except ValueError:
            print(f"[sheets] ID {entry_id} not found in sheet")
            return False

        label = STATUS_LABELS.get(status, status)
        sheet.update_cell(row_num, 7, label)   # col G = Statut
        if notes:
            sheet.update_cell(row_num, 8, notes)  # col H = Notes
        return True
    except RuntimeError as e:
        print(f"[sheets] Skipped: {e}")
        return False
    except Exception as e:
        print(f"[sheets] Error updating status: {e}")
        return False
