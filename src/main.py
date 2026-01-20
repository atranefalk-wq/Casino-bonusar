import os
import json
from typing import Dict, Any, List

from sources import fetch_page_text
from parse_terms import (
    extract_first_bonus_percent,
    extract_wagering_near,
    find_max_withdrawal_cap,
)
from sheets import (
    open_sheet,
    ensure_tabs_and_headers,
    clear_tab,
    write_rows,
    sort_and_rank,
    TABS,
)

def compute_score(bonus_percent: float, wagering_x: float) -> float:
    # Enkel ranking: hög bonus, låg wagering
    # Justera viktning efter smak
    return float(bonus_percent) - 0.5 * float(wagering_x)

def classify_row(row: Dict[str, Any]) -> str:
    """
    Prioritet:
      1) skrap om maxuttag hittas
      2) osakra om saknade fält / låg confidence
      3) bonus_over_50 / bonus_50_eller_mindre
    """
    if row.get("MaxUttagBonusvinster"):
        return "skrap"

    bonus = row.get("BonusProcent")
    wag = row.get("OmsattningsKrav")
    conf = row.get("Confidence", 0)

    # Om vi saknar kärnfält => osakra
    if bonus in (None, "", 0) or wag in (None, "", 0):
        return "osakra"

    # Om confidence är låg => osakra (tweakbar)
    if conf < 0.7:
        return "osakra"

    return "bonus_over_50" if float(bonus) > 50 else "bonus_50_eller_mindre"

def load_casinos(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    sheet_id = os.environ["SHEET_ID"]
    sa_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

    casinos = load_casinos("casinos.json")

    sh = open_sheet(sheet_id, sa_json)
    ensure_tabs_and_headers(sh)

    # Rensa flikar (behåll headers)
    for tab in TABS:
        clear_tab(sh, tab)

    buckets = {t: [] for t in TABS}

    for c in casinos:
        name = c.get("name", "").strip()
        url = c.get("url", "").strip()
        bonus_url = c.get("bonus_url", "").strip() or url

        base_row: Dict[str, Any] = {
            "Casino": name or url,
            "URL": url,
            "Kalla": bonus_url,
        }

        text, fetch_note = fetch_page_text(bonus_url)
        if not text:
            base_row.update({
                "BonusProcent": "",
                "OmsattningsKrav": "",
                "MaxUttagBonusvinster": "",
                "Confidence": 0.1,
                "ParsingNote": f"Kunde inte hämta sida. {fetch_note}",
                "Score": "",
            })
            tab = "osakra"
            buckets[tab].append(base_row)
            continue

        bonus_percent, anchor_pos, bonus_note, bonus_conf = extract_first_bonus_percent(text)
        wagering_x, wag_note, wag_conf = extract_wagering_near(text, anchor_pos if anchor_pos is not None else 0)
        cap_text, cap_note, cap_conf = find_max_withdrawal_cap(text, anchor_pos)

        # total confidence
        conf = min(bonus_conf, wag_conf)
        # maxuttag hittat är ofta tydligt — men om bara globalt så lägre conf
        if cap_text:
            conf = min(conf, cap_conf)

        parsing_notes = [fetch_note, bonus_note, wag_note, cap_note]
        note = " | ".join([n for n in parsing_notes if n])

        row = dict(base_row)
        row["BonusProcent"] = bonus_percent if bonus_percent is not None else ""
        row["OmsattningsKrav"] = wagering_x if wagering_x is not None else ""
        row["MaxUttagBonusvinster"] = cap_text if cap_text else ""
        row["Confidence"] = round(float(conf), 2)
        row["ParsingNote"] = note

        # score bara om vi har bra data och ingen cap
        if bonus_percent is not None and wagering_x is not None and not cap_text:
            row["Score"] = round(compute_score(bonus_percent, wagering_x), 4)
        else:
            row["Score"] = ""

        tab = classify_row(row)
        buckets[tab].append(row)

    # Skriv till sheets
    for tab_name, rows in buckets.items():
        write_rows(sh, tab_name, rows)

    # Sortera + ranka endast i bonusflikarna
    sort_and_rank(sh, "bonus_over_50")
    sort_and_rank(sh, "bonus_50_eller_mindre")

if __name__ == "__main__":
    main()
