import os
import json
from typing import Dict, Any, List, Tuple
from urllib.parse import urlparse

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

# -----------------------
# DEDUPE + NORMALIZATION
# -----------------------

def normalize_domain(url: str) -> str:
    """
    Normaliserar URL -> domän (utan www).
    Ex: https://www.example.com/sv/ -> example.com
    """
    try:
        u = urlparse((url or "").strip())
        host = (u.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return (url or "").strip().lower()


def dedupe_casino_list(casinos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicerar input-listan innan vi ens kör scraping.
    Key = domän från casino["url"] (fallback = url string).
    Behåller första förekomsten.
    """
    seen = set()
    out = []
    for c in casinos:
        url = (c.get("url") or "").strip()
        key = normalize_domain(url) or url.lower()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# -----------------------
# SCORING + CLASSIFICATION
# -----------------------

def compute_score(bonus_percent: float, wagering_x: float) -> float:
    # Hög bonus + låg wagering = bättre
    return float(bonus_percent) - 0.5 * float(wagering_x)


def classify_category(row: Dict[str, Any]) -> str:
    """
    Returnerar en kategori (utan licens-prefix):
      - skrap
      - osakra
      - bonus_over_50
      - bonus_50_eller_mindre
    """
    if row.get("MaxUttagBonusvinster"):
        return "skrap"

    bonus = row.get("BonusProcent")
    wag = row.get("OmsattningsKrav")
    conf = float(row.get("Confidence") or 0)

    # Saknas kärndata => osäkra
    if bonus in (None, "", 0) or wag in (None, "", 0):
        return "osakra"

    # Låg confidence => osäkra
    if conf < 0.7:
        return "osakra"

    return "bonus_over_50" if float(bonus) > 50 else "bonus_50_eller_mindre"


# Prioritet för vilken flik som "vinner" om ett casino skulle kunna hamna på flera ställen
CATEGORY_PRIORITY = {
    "skrap": 3,
    "osakra": 2,
    "bonus_over_50": 1,
    "bonus_50_eller_mindre": 1,
}


def _row_quality_tuple(row: Dict[str, Any]) -> Tuple[float, float]:
    """
    Används som tie-break när samma casino dyker upp flera gånger:
    1) högre Confidence vinner
    2) högre Score vinner
    """
    conf = float(row.get("Confidence") or 0)
    score = row.get("Score")
    try:
        score_val = float(score) if score not in (None, "") else -1e18
    except Exception:
        score_val = -1e18
    return conf, score_val


def choose_winner(existing: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Väljer mellan två rader för samma casino.
    1) kategori-prioritet
    2) confidence
    3) score
    """
    ex_cat = existing.get("_category", "osakra")
    ca_cat = candidate.get("_category", "osakra")

    ex_pri = CATEGORY_PRIORITY.get(ex_cat, 0)
    ca_pri = CATEGORY_PRIORITY.get(ca_cat, 0)

    if ca_pri > ex_pri:
        return candidate
    if ca_pri < ex_pri:
        return existing

    # Samma prioritet: välj bättre kvalitet
    ex_q = _row_quality_tuple(existing)
    ca_q = _row_quality_tuple(candidate)

    if ca_q > ex_q:
        return candidate
    return existing


# -----------------------
# IO
# -----------------------

def load_casinos(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# -----------------------
# MAIN
# -----------------------

def main():
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sa_json_b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")

    if not sheet_id:
        raise ValueError("SHEET_ID saknas. Sätt GitHub Secret SHEET_ID.")

    casinos = dedupe_casino_list(load_casinos("casinos.json"))

    sh = open_sheet(sheet_id, service_account_json=sa_json, service_account_json_b64=sa_json_b64)
    ensure_tabs_and_headers(sh)

    # Rensa alla tabs (behåll headers)
    for tab in TABS:
        clear_tab(sh, tab)

    # Global dedupe över ALLA tabs: 1 casino -> 1 final flik
    # key = domän -> row (inkl. vilken tab den ska till)
    winners_by_domain: Dict[str, Dict[str, Any]] = {}

    for c in casinos:
        name = (c.get("name") or "").strip()
        url = (c.get("url") or "").strip()
        bonus_url = (c.get("bonus_url") or "").strip() or url
        extract_cfg = c.get("extract")

        domain_key = normalize_domain(url) or url.lower()
        if not domain_key:
            # hoppa över helt trasiga entries
            continue

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
            row["_category"] = "osakra"
            row["_tab"] = "OKAND_osakra"
        else:
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
            lic_final = row.get("Licens") or "OKAND"
            tab = f"{lic_final}_{category}"

            row["_category"] = category
            row["_tab"] = tab

        # GLOBAL DEDUPE: välj vinnaren för domänen
        if domain_key not in winners_by_domain:
            winners_by_domain[domain_key] = row
        else:
            winners_by_domain[domain_key] = choose_winner(winners_by_domain[domain_key], row)

    # Bygg buckets från winners
    buckets: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TABS}

    for _, row in winners_by_domain.items():
        tab = row.get("_tab")
        if tab not in buckets:
            # Om licensen blev något oväntat: fallback
            tab = "OKAND_osakra"
        # ta bort interna fält
        row.pop("_tab", None)
        row.pop("_category", None)
        buckets[tab].append(row)

    # Skriv till sheets
    for tab_name, rows in buckets.items():
        write_rows(sh, tab_name, rows)

    # Sortera + ranka endast bonusflikarna
    for lic in LICENSES:
        sort_and_rank(sh, f"{lic}_bonus_over_50")
        sort_and_rank(sh, f"{lic}_bonus_50_eller_mindre")


if __name__ == "__main__":
    main()
