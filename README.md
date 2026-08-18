# YVR → BCN trip price checker

Free price tracking for your July 2027 Barcelona trip. Alerts email **bcw3bcw3@gmail.com**.

## Flights

| | |
|---|---|
| **From** | Vancouver (YVR) |
| **To** | Barcelona (BCN) |
| **Outbound** | **9, 10, 11, or 12 July 2027** |
| **Return** | **25 July 2027** |

| Cabin | Alert at or under |
|-------|-------------------|
| Economy | **CAD 1,100** |
| Premium economy | **CAD 1,600** |
| Business | **CAD 2,500** |

**Sources**
- **Google Flights** every ~5 minutes via [`fast-flights`](https://pypi.org/project/fast-flights/) (no key)
- **Skyscanner** once daily via [RapidAPI Sky Scrapper](https://rapidapi.com/apiheya/api/sky-scrapper) (needs free `RAPIDAPI_KEY`)

### Enable Skyscanner (free RapidAPI tier)

1. Create a [RapidAPI](https://rapidapi.com/) account and subscribe to **Sky Scrapper** (Basic / free).
2. Copy your RapidAPI key.
3. Repo secret: `RAPIDAPI_KEY`
4. Workflow: **Check Skyscanner prices** (daily 15:00 UTC, or run manually)

RapidAPI sometimes asks for a card even on free — stay on the free plan and watch the monthly request cap (~12 flight searches/day for this checker).

## Hotels (Barcelona — outside the cruise only)

Cruise **Jul 15–24** = nights on the ship (**not** tracked).

| Stay | Check-in → out | Why |
|------|----------------|-----|
| Pre-cruise | **Jul 11→15** | Land Jul 11 until cruise embark |
| Post-cruise | **Jul 24→25** | After ship, before Jul 25 flight home |

- Source: Google Hotels via [`stays`](https://pypi.org/project/stays/)
- Filter: **3★+** major chains only (**Marriott, Hyatt, Accor, Hilton, IHG, Four Seasons**), within **4 km of Plaça de Catalunya**
- Email alert when cheapest is **≤ CAD 200 / night**
- Far-out July 2027 rates are often **placeholders**. Alerts only fire when Google returns a real **OTA booking link** (Expedia/Booking/etc.), and list prices are treated as **per night** (not divided by stay length).

**Cost: $0.** Flights: Google (`fast-flights`) + optional Skyscanner (RapidAPI free). Hotels: `stays`. No paid flight APIs.

## Stay at $0 on GitHub

1. Prefer a **public** repo → Actions minutes are free.
2. Or keep it private and stay under **2,000 free minutes/month**.
3. In GitHub: **Settings → Billing → Budgets** → set Actions budget to **$0**.

### Enable email (free, no credit card)

1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification)
2. Create an [App Password](https://myaccount.google.com/apppasswords)
3. Repo secrets: `GMAIL_USER`, `GMAIL_APP_PASSWORD`

### Biweekly summary

On the **1st and 15th**, email with daily lows for flights (all cabins) + both hotel stays over the past 14 days.

## Important caveats

- July 2027 inventory can be thin or placeholder early on.
- GitHub cloud IPs sometimes get blocked by Google — retries usually recover.
- Skyscanner needs `RAPIDAPI_KEY`; free tier has a monthly request cap.
- Confirm on Google Flights / Skyscanner / Hotels before booking.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python check_flights.py
python check_hotels.py
RAPIDAPI_KEY=... python check_skyscanner.py
```

## Schedule

- **Every 5 minutes:** Google Flights + hotels
- **Daily 15:00 UTC:** Skyscanner (quota-safe)

## Files

| Path | Role |
|------|------|
| `check_flights.py` | Google Flights fares by cabin |
| `check_skyscanner.py` | Skyscanner fares by cabin (daily) |
| `check_hotels.py` | Barcelona hotels for landing nights + post-cruise |
| `send_biweekly_summary.py` | 14-day email summary |
| `.github/workflows/check-flights.yml` | Google + hotels |
| `.github/workflows/check-skyscanner.yml` | Skyscanner daily |
| `data/history.jsonl` | Google flight history |
| `data/skyscanner_history.jsonl` | Skyscanner flight history |
| `data/hotel_history.jsonl` | Hotel history |
