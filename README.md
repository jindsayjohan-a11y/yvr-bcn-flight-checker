# YVR → BCN trip price checker

Free price tracking for your July 2027 Barcelona trip. Alerts email **bcw3bcw3@gmail.com**.

## Flights

| | |
|---|---|
| **From** | Vancouver (YVR) |
| **To** | Barcelona (BCN) |
| **Outbound** | 16, 17, or 18 July **2027** |
| **Return** | 25 July **2027** |

| Cabin | Alert at or under |
|-------|-------------------|
| Economy | **CAD 1,100** |
| Premium economy | **CAD 1,600** |
| Business | **CAD 2,500** |

## Hotels (Barcelona — outside the cruise only)

Cruise is **July 15–24** (nights on the ship). Those dates are **not** tracked for hotels.

| Stay | Check-in | Check-out | Why |
|------|----------|-----------|-----|
| Pre-cruise | **2027-07-14** | **2027-07-15** | Night before embarkation |
| Post-cruise | **2027-07-24** | **2027-07-25** | Disembark → overnight before July 25 flight home |

Hotel alert: cheapest 1-night total **≤ CAD 300** (2 adults, Google Hotels via [`stays`](https://pypi.org/project/stays/)).

**Cost: $0.** Flights use [`fast-flights`](https://pypi.org/project/fast-flights/); hotels use `stays`. No credit card.

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
- Confirm on Google Flights / Hotels before booking.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python check_flights.py
python check_hotels.py
```

## Schedule

**Every 5 minutes** (GitHub’s shortest cron). Flights + hotels run in the same workflow.

## Files

| Path | Role |
|------|------|
| `check_flights.py` | Flight fares by cabin |
| `check_hotels.py` | Barcelona hotels pre/post cruise only |
| `send_biweekly_summary.py` | 14-day email summary |
| `.github/workflows/check-flights.yml` | Scheduled checker |
| `data/history.jsonl` | Flight history |
| `data/hotel_history.jsonl` | Hotel history |
