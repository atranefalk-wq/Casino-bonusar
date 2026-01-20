import requests
from bs4 import BeautifulSoup
from typing import Tuple, Optional

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CasinoSheetsBot/1.0; +https://github.com/)",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}

def fetch_page_text(url: str, timeout: int = 25) -> Tuple[Optional[str], str]:
    """
    Hämtar sidan och returnerar (text, note).
    """
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        return None, f"Fetch-fel: {e}"

    soup = BeautifulSoup(r.text, "lxml")

    # Ta bort script/style för renare text
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # Gör texten lite mer regex-vänlig
    text = " ".join(text.split())

    if len(text) < 200:
        return text, "VARNING: Väldigt lite text hittades (kan vara dynamiskt innehåll)"
    return text, "OK"
