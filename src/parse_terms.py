import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

CASINO_BONUS_KEYWORDS = [
    "välkomstbonus", "insättningsbonus", "bonus", "casino bonus",
    "welcome bonus", "deposit bonus", "bonus terms",
    "bonusvillkor", "kampanjvillkor",
]

NON_BONUS_CONTEXT_RED_FLAGS = [
    "rtp", "återbetalning", "payback", "cashback", "rabatt", "apr", "ränta",
]

@dataclass
class BonusHit:
    percent: int
    start: int
    context: str

def _looks_like_casino_bonus_context(context: str) -> bool:
    c = context.lower()
    if not any(k in c for k in CASINO_BONUS_KEYWORDS):
        return False
    # Om det ser mer ut som RTP/cashback än bonus
    if any(rf in c for rf in NON_BONUS_CONTEXT_RED_FLAGS) and ("bonus" not in c and "välkomstbonus" not in c):
        return False
    return True

BONUS_PATTERNS = [
    r'(\d{1,3})\s*%\s*(?:välkomstbonus|insättningsbonus|bonus|casino bonus|welcome bonus|deposit bonus)',
    r'(?:välkomstbonus|insättningsbonus|bonus|casino bonus|welcome bonus|deposit bonus)\s*[:\-]?\s*(\d{1,3})\s*%',
    r'(?:få|get)\s+(\d{1,3})\s*%\s*(?:upp till|bonus|welcome|deposit)',
]

def extract_first_bonus_percent(text: str) -> Tuple[Optional[int], Optional[int], str, float]:
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
        note += f" | {len(hits)} bonus-träffar hittades, valde tidigaste"
        conf = 0.80

    return first.percent, first.start, note, conf

def extract_wagering_near(text: str, anchor_pos: int, window: int = 2800) -> Tuple[Optional[float], str, float]:
    t = text.lower()
    segment = t[anchor_pos:anchor_pos + window] if anchor_pos is not None else t[:window]

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

    # fallback globalt med lägre confidence
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).replace(",", ".")
            try:
                val = float(raw)
                if 0 < val < 1000:
                    return val, "Omsättningskrav hittades globalt (osäkrare koppling)", 0.55
            except ValueError:
                pass

    return None, "Omsättningskrav hittades inte", 0.3

def find_max_withdrawal_cap(text: str, anchor_pos: Optional[int], window: int = 3500) -> Tuple[Optional[str], str, float]:
    t = text.lower().replace("curaçao", "curacao")

    segment = t[anchor_pos:anchor_pos + window] if anchor_pos is not None else None

    cap_patterns = [
        r'(maxuttag|max uttag|maximalt uttag)[^.\n]{0,140}',
        r'(max withdrawal|withdrawal cap|maximum withdrawal)[^.\n]{0,140}',
        r'(tak för uttag|uttakstak|vinsttak)[^.\n]{0,140}',
    ]
    money_hint = re.compile(r'(\d[\d\s\.,]{0,12})\s*(sek|kr|eur|€|\$|usd|gbp|£)', re.IGNORECASE)

    def scan(s: str) -> Optional[str]:
        for p in cap_patterns:
            m = re.search(p, s, flags=re.IGNORECASE)
            if m:
                snippet = m.group(0).strip()
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

def extract_license(text: str) -> Tuple[str, float, str]:
    t = text.lower().replace("curaçao", "curacao")

    mga_patterns = [
        r"malta gaming authority",
        r"\bmga\b",
        r"licensed.*malta",
        r"regulated.*malta",
    ]
    curacao_patterns = [
        r"\bcuracao\b",
        r"curacao egaming",
        r"antillephone",
        r"gaming curacao",
        r"master license",
        r"\b8048/jaz\b",
        r"\b365/jaz\b",
    ]

    def any_match(patterns):
        return any(re.search(p, t, flags=re.IGNORECASE) for p in patterns)

    is_mga = any_match(mga_patterns)
    is_cur = any_match(curacao_patterns)

    if is_mga and not is_cur:
        return "MGA", 0.9, "Licens hittad: MGA"
    if is_cur and not is_mga:
        return "CURACAO", 0.9, "Licens hittad: Curacao"
    if is_mga and is_cur:
        return "OTHER", 0.55, "Flera licens-indikationer hittades (MGA + Curacao) – osäkert"
    return "OKAND", 0.3, "Licens hittades inte"
