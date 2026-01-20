import os
import json
from typing import Dict, Any, List

from src.sources import fetch_text_with_adapter
from src.parse_terms import (
    extract_first_bonus_percent,
    extract_wagering_near,
    find_max_withdrawal_cap,
    extract_license,
)
from src.sheets import (
    open_sheet,
    ensure_tabs_and_headers,
    clear_tab,
    write_rows,
    sort_and_rank,
    TABS,
    LICENSES,
)

def compute_score(bonus_percent: float, wagering_x: float) -> float:
    return float(bonus_percent) - 0.5 * float(wagering_x)

def classify_category(row: Dict[str, Any]) -> str:
    if row.get("MaxUttagBonusvinster"):
        return "skrap"

    bonus = row.get("BonusProcent")
    wag = row.get("OmsattningsKrav")
    conf = float(row.get("Confidence") or 0)

    if bonus in (None, "", 0) or wag in (None, "", 0):
        return "osakra"
    if conf < 0.7:
        return "osakra"

    return "bonus_over_50" if float(bonus) > 50 else "bonus_50_eller_mindre"

def load_casinos(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sa_json_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")

    if not sheet_id:
        raise ValueError("SHEET_ID saknas. Sätt GitHub Secret SHEET_ID.")

    casinos = load_casinos("casinos.json")

    sh = open_sheet(sheet_id, service_account_json=sa_json, service_account_json_b64=sa_json_b64)
    ensure_tabs_and_headers(sh)

    for tab in TABS:
        clear_tab(sh, tab)

    buckets = {t: [] for t in TABS}

    for c in casinos:
        name = (c.get("name") or "").strip()
        url = (c.get("url") or "").strip()
        bonus_url = (c.get("bonus_url") or "").strip() or url
        extract_cfg = c.get("extract")

        base_row: Dict[str, Any] = {
            "Casino": name or url,
            "URL": url,
            "Kalla": bonus_url,
        }

        text, fetch_note, final_url = fetch_text_with_adapter(bonus_url, extract_cfg=extract_cfg)
        base_row["Kalla"] = final_url

        if not text:
            row = dict(base_row)
            row.update({
                "Licens": "OKAND",
                "LicenseConfidence": 0.1,
                "BonusProcent": "",
                "OmsattningsKrav": "",
                "MaxUttagBonusvinster": "",
                "Confidence": 0.1,
                "ParsingNote": f"Kunde inte hämta sida. {fetch_note}",
                "Score": "",
            })
            tab = "OKAND_osakra"
            buckets[tab].append(row)
            continue

        lic, lic_conf, lic_note = extract_license(text)

        bonus_percent, anchor_pos, bonus_note, bonus_conf = extract_first_bonus_percent(text)
        wagering_x, wag_note, wag_conf = extract_wagering_near(text, anchor_pos if anchor_pos is not None else 0)
        cap_text, cap_note, cap_conf = find_max_withdrawal_cap(text, anchor_pos)

        conf = min(bonus_conf, wag_conf)
        if cap_text:
            conf = min(conf, cap_conf)

        row = dict(base_row)
        row["Licens"] = lic
        row["LicenseConfidence"] = round(float(lic_conf), 2)
        row["BonusProcent"] = bonus_percent if bonus_percent is not None else ""
        row["OmsattningsKrav"] = wagering_x if wagering_x is not None else ""
        row["MaxUttagBonusvinster"] = cap_text if cap_text else ""
        row["Confidence"] = round(float(conf), 2)

        parsing_notes = [fetch_note, lic_note, bonus_note, wag_note, cap_note]
        row["ParsingNote"] = " | ".join([n for n in parsing_notes if n])

        if bonus_percent is not None and wagering_x is not None and not cap_text:
            row["Score"] = round(compute_score(bonus_percent, wagering_x), 4)
        else:
            row["Score"] = ""

        category = classify_category(row)
        tab = f"{lic}_{category}"
        buckets[tab].append(row)

    for tab_name, rows in buckets.items():
        write_rows(sh, tab_name, rows)

    for lic in LICENSES:
        sort_and_rank(sh, f"{lic}_bonus_over_50")
        sort_and_rank(sh, f"{lic}_bonus_50_eller_mindre")

if __name__ == "__main__":
    main()
