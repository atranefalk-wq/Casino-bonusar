import json
from typing import List, Dict, Any
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

TABS = ["bonus_over_50", "bonus_50_eller_mindre", "skrap", "osakra"]

COLUMNS = [
    "Rank",
    "Casino",
    "URL",
    "BonusProcent",
    "OmsattningsKrav",
    "MaxUttagBonusvinster",
    "Confidence",
    "ParsingNote",
    "Kalla",
    "SenastUppdaterad",
    "Score"
]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def open_sheet(sheet_id: str, service_account_json: str):
    creds_info = json.loads(service_account_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    return sh

def ensure_tabs_and_headers(sh):
    existing = {ws.title: ws for ws in sh.worksheets()}

    for tab in TABS:
        if tab not in existing:
            sh.add_worksheet(title=tab, rows=2000, cols=len(COLUMNS) + 5)

    # Refresh map after possibly adding
    existing = {ws.title: ws for ws in sh.worksheets()}

    for tab in TABS:
        ws = existing[tab]
        # Skriv headers i rad 1
        ws.resize(rows=max(ws.row_count, 2), cols=max(ws.col_count, len(COLUMNS)))
        ws.update(values=[COLUMNS], range_name=f"A1:{chr(64+len(COLUMNS))}1")

def clear_tab(sh, tab_name: str):
    ws = sh.worksheet(tab_name)
    # Behåll header-raden, rensa resten
    if ws.row_count > 1:
        ws.batch_clear([f"A2:{chr(64+len(COLUMNS))}{ws.row_count}"])

def write_rows(sh, tab_name: str, rows: List[Dict[str, Any]]):
    ws = sh.worksheet(tab_name)
    values = []
    for r in rows:
        values.append([
            r.get("Rank", ""),
            r.get("Casino", ""),
            r.get("URL", ""),
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
    end_col_letter = chr(64 + len(COLUMNS))
    ws.update(values=values, range_name=f"A{start_row}:{end_col_letter}{end_row}")

def sort_and_rank(sh, tab_name: str):
    """
    Sortera på Score (desc) och sätt Rank 1..N
    Förutsätter att data börjar på rad 2.
    """
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

    def score_of(row):
        try:
            return float(row[score_idx]) if row[score_idx] != "" else -1e18
        except Exception:
            return -1e18

    rows.sort(key=score_of, reverse=True)

    # Sätt rank
    for i, row in enumerate(rows, start=1):
        if len(row) <= rank_idx:
            # säkerställ längd
            row.extend([""] * (rank_idx - len(row) + 1))
        row[rank_idx] = str(i)

    # Skriv tillbaka hela tabellen (header + rows)
    ws.update(values=[header] + rows, range_name=f"A1:{chr(64+len(header))}{len(rows)+1}")
