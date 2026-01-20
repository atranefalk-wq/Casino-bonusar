import json
import base64
from typing import List, Dict, Any
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

LICENSES = ["MGA", "CURACAO", "OKAND", "OTHER"]
CATEGORIES = ["bonus_over_50", "bonus_50_eller_mindre", "skrap", "osakra"]
TABS = [f"{lic}_{cat}" for lic in LICENSES for cat in CATEGORIES]

COLUMNS = [
    "Rank",
    "Casino",
    "URL",
    "Licens",
    "LicenseConfidence",
    "BonusProcent",
    "OmsattningsKrav",
    "MaxUttagBonusvinster",
    "Confidence",
    "ParsingNote",
    "Kalla",
    "SenastUppdaterad",
    "Score",
]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _col_letter(n: int) -> str:
    if n <= 0:
        raise ValueError("n must be >= 1")
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def open_sheet(sheet_id: str, service_account_json: str = "", service_account_json_b64: str = ""):
    """
    Stödjer både raw JSON i env och base64 i env (rekommenderat i GitHub).
    """
    if service_account_json_b64 and not service_account_json:
        try:
            decoded = base64.b64decode(service_account_json_b64).decode("utf-8")
            service_account_json = decoded
        except Exception as e:
            raise ValueError(f"Kunde inte base64-dekoda service account json: {e}")

    if not service_account_json or not service_account_json.strip():
        raise ValueError("Service account JSON är tom. Kontrollera GitHub Secret(s).")

    service_account_json = service_account_json.strip()

    try:
        creds_info = json.loads(service_account_json)
    except json.JSONDecodeError as e:
        raise ValueError(
            "Service account JSON är inte giltig JSON. "
            "Kontrollera att secret innehåller hela JSON-filen (bör börja med '{'). "
            f"JSON error: {e}"
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)

def ensure_tabs_and_headers(sh):
    existing = {ws.title: ws for ws in sh.worksheets()}

    for tab in TABS:
        if tab not in existing:
            sh.add_worksheet(title=tab, rows=2000, cols=len(COLUMNS) + 5)

    existing = {ws.title: ws for ws in sh.worksheets()}
    end_col_letter = _col_letter(len(COLUMNS))

    for tab in TABS:
        ws = existing[tab]
        ws.resize(rows=max(ws.row_count, 2), cols=max(ws.col_count, len(COLUMNS)))
        ws.update(values=[COLUMNS], range_name=f"A1:{end_col_letter}1")

def clear_tab(sh, tab_name: str):
    ws = sh.worksheet(tab_name)
    end_col_letter = _col_letter(len(COLUMNS))
    if ws.row_count > 1:
        ws.batch_clear([f"A2:{end_col_letter}{ws.row_count}"])

def write_rows(sh, tab_name: str, rows: List[Dict[str, Any]]):
    ws = sh.worksheet(tab_name)
    values = []

    for r in rows:
        values.append([
            r.get("Rank", ""),
            r.get("Casino", ""),
            r.get("URL", ""),
            r.get("Licens", ""),
            r.get("LicenseConfidence", ""),
            r.get("BonusProcent", ""),
            r.get("OmsattningsKrav", ""),
            r.get("MaxUttagBonusvinster", ""),
            r.get("Confidence", ""),
            r.get("ParsingNote", ""),
            r.get("Kalla", ""),
            r.get("SenastUppdaterad", _now_iso()),
            r.get("Score", ""),
        ])

    if not values:
        return

    start_row = 2
    end_row = start_row + len(values) - 1
    end_col_letter = _col_letter(len(COLUMNS))
    ws.update(values=values, range_name=f"A{start_row}:{end_col_letter}{end_row}")

def sort_and_rank(sh, tab_name: str):
    ws = sh.worksheet(tab_name)
    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        return

    header = all_values[0]
    rows = all_values[1:]

    try:
        score_idx = header.index("Score")
        rank_idx = header.index("Rank")
    except ValueError:
        return

    def score_of(row: List[str]) -> float:
        try:
            s = row[score_idx] if score_idx < len(row) else ""
            return float(s) if s != "" else -1e18
        except Exception:
            return -1e18

    rows.sort(key=score_of, reverse=True)

    for i, row in enumerate(rows, start=1):
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        row[rank_idx] = str(i)

    end_col_letter = _col_letter(len(header))
    ws.update(values=[header] + rows, range_name=f"A1:{end_col_letter}{len(rows)+1}")
