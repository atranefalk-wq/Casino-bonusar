## Casino → Google Sheets (bonus, wagering, maxuttag)

Scriptet:
- Hämtar text från casino-URL (eller bonus_url om angiven)
- Tar **första CASINO-bonusen** som nämns i texten (antagen välkomstbonus)
- Plockar bonusprocent, omsättningskrav och ev. maxuttag på bonusvinster
- Skriver till Google Sheets i flikarna:
  - bonus_over_50
  - bonus_50_eller_mindre
  - skrap (maxuttag/cap hittat)
  - osakra (saknar data/låg confidence)

### Setup
1) Skapa Google Cloud Service Account + Sheets API
2) Dela ditt Google Sheet med service account-mailen (Editor)
3) Sätt GitHub Secrets:
   - SHEET_ID
   - GOOGLE_SERVICE_ACCOUNT_JSON (hela json-nyckeln)

4) Lägg in casinon i `casinos.json`

### Kör lokalt
export SHEET_ID="..."
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ...}'
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python src/main.py
