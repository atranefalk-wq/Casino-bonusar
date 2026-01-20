import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

# Vi vill vara säkra på att det handlar om casino-bonus (inte RTP, cashback, etc).
CASINO_BONUS_KEYWORDS = [
    "välkomstbonus",
    "insättningsbonus",
    "bonus",
    "casino bonus",
    "casinoerbjudande",
    "welcome bonus",
    "deposit bonus",
    "bonus terms",
    "bonusvillkor",
    "kampanjvillkor",
]

# Ord som ofta dyker upp när procenten INTE är casino-bonus
NON_BONUS_CONTEXT_RED_FLAGS = [
    "rtp",
    "återbetalning",
    "payback",
    "återbäring",
    "cashback",
    "rabatt",
    "ränta",
    "apr",
    "free spins",  # free spins kan vara bonus men procenttal + free spins brukar vara ovanligt
]

@dataclass
class BonusHit:
    percent: int
    start: int
    context: str

def _looks_like_casino_bonus_context(context: str) -> bool:
    c = context.lower()
    # Måste ha minst ett bonus/casino-relaterat keyword i närheten
    if not any(k in c for k in CASINO_BONUS_KEYWORDS):
        return False
    # Om den är full av tydliga "inte bonus"-indikatorer -> underkänn
    if any(rf in c for rf in NON_BONUS_CONTEXT_RED_FLAGS) and ("bonus" not in c and "välkomstbonus" not in c):
        return False
    return True

BONUS_PATTERNS = [
    # "100% välkomstbonus", "100 % bonus"
    r'(\d{1,3})\s*%\s*(?:välkomstbonus|insättningsbonus|bonus|casino bonus|welcome bonus|deposit bonus)',
    # "Välkomstbonus: 100%"
    r'(?:välkomstbonus|insättningsbonus|bonus|casino bonus|welcome bonus|deposit bonus)\s*[:\-]?\s*(\d{1,3})\s*%',
    # "Få 100% upp till ..."
    r'(?:få|get)\s+(\d{1,3})\s*%\s*(?:upp till|bonus|welcome|deposit)',
]

def extract_first_bonus_percent(text: str) -> Tuple[Optional[int], Optional[int], str, float]:
    """
    Returnerar:
      (bonus_percent, anchor_pos, note, confidence)

    Tar den tidigast förekommande matchen i texten som ser ut att vara CASINO-bonus.
    """
    t = text.lower()
    hits: List[BonusHit] = []

    for pat in BONUS_PATTERNS:
        for m in re.finditer(pat, t, flags=re.IGNORECASE):
            try:
                val = int(m.group(1))
            except Exception:
                continue
            if not (1 <= val <= 500):
                continue

            start = m.start()
            context = t[max(0, start - 80):min(len(t), start + 160)]
            if _looks_like_casino_bonus_context(context):
                hits.append(BonusHit(percent=val, start=start, context=context))

    if not hits:
        return None, None, "Ingen casino-bonusprocent hittades (eller ej tydligt casino-bonus)", 0.2

    hits.sort(key=lambda h: h.start)
    first = hits[0]

    note = "Första casino-bonus i texten valdes (antagen välkomstbonus)"
    conf = 0.85

    if len(hits) > 1:
        note += f" | {len(hits)} casino-bonus-träffar hittades, valde tidigaste"
        conf = 0.80  # liten sänkning (kan finnas flera bonusar)

    return first.percent, first.start, note, conf

def extract_wagering_near(text: str, anchor_pos: int, window: int = 2800) -> Tuple[Optional[float], str, float]:
    """
    Försöker hitta omsättningskrav nära första bonusen.
    Returnerar (wagering_x, note, confidence)
    """
    t = text.lower()
    if anchor_pos is None:
        return None, "Saknar anchor_pos för bonus", 0.2

    segment = t[anchor_pos:anchor_pos + window]

    patterns = [
        r'(\d+(?:[.,]\d+)?)\s*x',
        r'omsättningskrav[^0-9]{0,40}(\d+(?:[.,]\d+)?)',
        r'(\d+(?:[.,]\d+)?)\s*(?:gånger|times)\b'
    ]

    for p in patterns:
        m = re.search(p, segment, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", ".")
            try:
                val = float(raw)
                if 0 < val < 1000:
                    return val, "Omsättningskrav hittades nära första bonusen", 0.85
            except ValueError:
                pass

    # fallback: global sökning men lägre confidence
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", ".")
            try:
                val = float(raw)
                if 0 < val < 1000:
                    return val, "Omsättningskrav hittades globalt (ej säkert kopplat till välkomstbonus)", 0.55
            except ValueError:
                pass

    return None, "Omsättningskrav hittades inte", 0.3

def find_max_withdrawal_cap(text: str, anchor_pos: Optional[int], window: int = 3500) -> Tuple[Optional[str], str, float]:
    """
    Letar efter maxuttag/cap på bonusvinster.
    Om vi hittar något => "skrap".

    Returnerar (cap_text, note, confidence)
    """
    t = text.lower()

    # Fönster nära bonusen först
    segment = None
    if anchor_pos is not None:
        segment = t[anchor_pos:anchor_pos + window]

    cap_patterns = [
        r'(maxuttag|max uttag|maximalt uttag)[^.\n]{0,120}',
        r'(max withdrawal|withdrawal cap|maximum withdrawal)[^.\n]{0,120}',
        r'(tak för uttag|uttakstak|vinsttak)[^.\n]{0,120}',
    ]

    money_hint = re.compile(r'(\d[\d\s\.,]{0,12})\s*(sek|kr|eur|€|\$|usd|gbp|£)', re.IGNORECASE)

    def scan(s: str) -> Optional[str]:
        for p in cap_patterns:
            m = re.search(p, s, flags=re.IGNORECASE)
            if m:
                snippet = m.group(0).strip()
                # extra signal: om pengar finns i närheten
                nearby = s[m.start():min(len(s), m.start()+200)]
                if money_hint.search(nearby):
                    return snippet + " (pengabelopp hittat)"
                return snippet
        return None

    if segment:
        found = scan(segment)
        if found:
            return found, "Maxuttag/cap hittades nära bonusvillkoren", 0.9

    found_global = scan(t)
    if found_global:
        return found_global, "Maxuttag/cap hittades globalt (osäkrare koppling)", 0.65

    return None, "Inget maxuttag/cap hittades", 0.85
