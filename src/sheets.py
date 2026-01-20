import json
from typing import List, Dict, Any
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

# Licenser vi separerar på (du kan lägga till fler senare)
LICENSES = ["MGA", "CURACAO", "OKAND", "OTHER"]

# Kategorier (som tidigare)
CATEGORIES = ["bonus_over_50", "bonus_50_eller_mindre", "skrap", "osakra"]

# Alla flikar som scriptet kommer skapa/skriva till
TABS = [f"{lic}_{cat}" for lic in LICENSES for cat in CATEGORIES]

# Kolumner (samma i alla flikar)
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


def open_sheet(sheet_id: str, service_account_json: str):
    """
    Öppnar Google Sheet via service account JSON (som sträng).
    """
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
    """
    Skapar flikar som saknas och skriver header-raden i varje flik.
    """
    existing = {ws.title: ws for ws in sh.worksheets()}

    # Skapa saknade flikar
    for tab in TABS:
        if tab not in existing:
            sh.add_worksheet(title=tab, rows=2000, cols=len(COLUMNS) + 5)

    # Refresh map efter ev. skapande
    existing = {ws.title: ws for ws in sh.worksheets()}

    # Skriv headers
    end_col_letter = _col_letter(len(COLUMNS))
    for tab in TABS:
        ws = existing[tab]
        ws.resize(rows=max(ws.row_count, 2), cols=max(ws.col_count, len(COLUMNS)))
        ws.update(values=[COLUMNS], range_name=f"A1:{end_col_letter}1")


def clear_tab(sh, tab_name: str):
    """
    Rensar innehåll från rad 2 och nedåt (behåller headers).
    """
    ws = sh.worksheet(tab_name)
    end_col_letter = _col_letter(len(COLUMNS))
    if ws.row_count > 1:
        ws.batch_clear([f"A2:{end_col_letter}{ws.row_count}"])


def write_rows(sh, tab_name: str, rows: List[Dict[str, Any]]):
    """
    Skriver rows (dict) från rad 2 i den givna fliken.
    """
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
    """
    Sorterar tabellen på Score (desc) och sätter Rank = 1..N.
    Förutsätter header i rad 1 och data från rad 2.
    """
    ws = sh.worksheet(tab_name)
    all_values = ws.get_all_values()

    if len(all_values) <= 1:
        return  # ingen data

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

    # Sätt rank
    for i, row in enumerate(rows, start=1):
        # säkra längd
        if len(row) < len(header):
            row.extend([""] * (len(header) - len(row)))
        row[rank_idx] = str(i)

    end_col_letter = _col_letter(len(header))
    ws.update(values=[header] + rows, range_name=f"A1:{end_col_letter}{len(rows)+1}")


def _col_letter(n: int) -> str:
    """
    1 -> A, 2 -> B, ... 26 -> Z, 27 -> AA, ...
    """
    if n <= 0:
        raise ValueError("n must be >= 1")
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
