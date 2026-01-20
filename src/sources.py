import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import Tuple, Optional, Dict, Any, List

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CasinoSheetsBot/1.0; +https://github.com/)",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}

def _clean_soup(soup: BeautifulSoup) -> None:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

def _get_text_from_selectors(soup: BeautifulSoup, selectors: List[str]) -> Tuple[Optional[str], str]:
    for sel in selectors:
        nodes = soup.select(sel)
        if nodes:
            text = " ".join([n.get_text(" ", strip=True) for n in nodes])
            text = " ".join(text.split())
            if len(text) >= 200:
                return text, f"OK: selector träffade: {sel}"
            else:
                return text, f"VARNING: selector {sel} gav lite text"
    return None, "Inga selectors matchade"

def _find_link_by_text(soup: BeautifulSoup, base_url: str, contains_terms: List[str]) -> Optional[str]:
    terms = [t.lower() for t in contains_terms]
    for a in soup.find_all("a", href=True):
        txt = (a.get_text(" ", strip=True) or "").lower()
        if any(t in txt for t in terms):
            return urljoin(base_url, a["href"])
    return None

def _regex_block(text: str, start_regex: str, end_regex: str, max_chars: int = 15000) -> Tuple[Optional[str], str]:
    t = text.lower()
    s = re.search(start_regex.lower(), t, flags=re.IGNORECASE)
    if not s:
        return None, "regex_block: start hittades inte"
    start = s.start()
    e = re.search(end_regex.lower(), t[start:], flags=re.IGNORECASE)
    end = start + e.start() if e else min(len(t), start + max_chars)
    block = text[start:end]
    block = " ".join(block.split())
    if len(block) < 200:
        return block, "regex_block: hittade block men kort"
    return block[:max_chars], "OK: regex_block"

def fetch_text_with_adapter(url: str, extract_cfg: Optional[Dict[str, Any]] = None, timeout: int = 25) -> Tuple[Optional[str], str, str]:
    """
    Returnerar (text, note, final_url_used)
    """
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        return None, f"Fetch-fel: {e}", url

    soup = BeautifulSoup(r.text, "lxml")
    _clean_soup(soup)

    mode = (extract_cfg or {}).get("mode", "fullpage")

    if mode == "selectors":
        selectors = extract_cfg.get("selectors", ["main", "article", "body"])
        text, note = _get_text_from_selectors(soup, selectors)
        if text:
            return text, note, url
        full = " ".join(soup.get_text(" ", strip=True).split())
        return full, f"{note} | fallback fullpage", url

    if mode == "link_then_selectors":
        contains_terms = extract_cfg.get("link_text_contains", ["bonusvillkor", "villkor", "terms"])
        link = _find_link_by_text(soup, url, contains_terms)
        if link:
            try:
                r22 = requests.get(link, headers=DEFAULT_HEADERS, timeout=timeout)
                r2.raise_for_status()
                soup2 = BeautifulSoup(r2.text, "lxml")
                _clean_soup(soup2)
                selectors = extract_cfg.get("selectors", ["main", "article", "body"])
                text, note = _get_text_from_selectors(soup2, selectors)
                if text:
                    return text, f"OK: följde länk -> {note}", link
                full2 = " ".join(soup2.get_text(" ", strip=True).split())
                return full2, f"Följde länk men {note} | fallback fullpage", link
            except Exception as e:
                full = " ".join(soup.get_text(" ", strip=True).split())
                return full, f"Följde länk men fetch-fel: {e} | fallback ursprungssida", url
        full = " ".join(soup.get_text(" ", strip=True).split())
        return full, "Hittade ingen villkorslänk | fallback fullpage", url

    if mode == "regex_block":
        full = " ".join(soup.get_text(" ", strip=True).split())
        start_regex = extract_cfg.get("start_regex", "bonusvillkor")
        end_regex = extract_cfg.get("end_regex", "ansvar")
        max_chars = int(extract_cfg.get("max_chars", 15000))
        block, note = _regex_block(full, start_regex, end_regex, max_chars=max_chars)
        if block:
            return block, note, url
        return full, f"{note} | fallback fullpage", url

    full = " ".join(soup.get_text(" ", strip=True).split())
    return full, "OK: fullpage", url
