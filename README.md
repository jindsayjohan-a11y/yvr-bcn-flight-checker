# YVR → BCN flight price checker

Daily (and on-demand) price checks for:

| | |
|---|---|
| **From** | Vancouver (YVR) |
| **To** | Barcelona (BCN) |
| **Outbound** | 16, 17, or 18 July **2027** |
| **Return** | 25 July **2027** |

**Cost: $0.** Prices come from Google Flights via [`fast-flights`](https://pypi.org/project/fast-flights/). Alerts email **bcw3bcw3@gmail.com** when fares hit the threshold.

## Stay at $0 on GitHub

1. Prefer a **public** repo → Actions minutes are free.
2. Or keep it private and stay under **2,000 free minutes/month** (daily checks use ~30).
3. In GitHub: **Settings → Billing → Budgets** → set Actions budget to **$0** so nothing can ever charge.

## Price alerts (≤ CAD 1100)

When the cheapest round-trip is **at or under CAD 1,100**:

1. **Email** to `bcw3bcw3@gmail.com` (needs Gmail App Password secrets below)
2. GitHub **Issue** labeled `price-alert` as backup

### Enable email (free, no credit card)

Gmail won’t let GitHub send mail with your normal password. Use an **App Password**:

1. Sign into the Google account that will **send** the mail (can be `bcw3bcw3@gmail.com`)
2. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification) if it isn’t already
3. Create an [App Password](https://myaccount.google.com/apppasswords) → app “Mail” → copy the 16-character password
4. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   - `GMAIL_USER` = that Gmail address (e.g. `bcw3bcw3@gmail.com`)
   - `GMAIL_APP_PASSWORD` = the 16-character app password (no spaces)

Alerts are sent **to** `bcw3bcw3@gmail.com` automatically.

## Important caveats

- **July 2027 may show “no offers” for a while.** Airlines often open schedules ~10–11 months ahead. The daily job will start returning prices once Google has them.
- **GitHub’s servers sometimes get blocked by Google.** If Actions runs fail with “no flights” while your laptop works, run locally instead (below) or keep retrying daily — blocks come and go.
- Prices are for research only; always confirm on Google Flights / the airline before booking.

## Run locally (most reliable free option)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python check_flights.py
```

Your home IP is less likely to be blocked than a cloud datacenter.

## Schedule

Default: **once per day** (~8am Pacific). That is plenty for fare watching and stays safely free.

## Files

| Path | Role |
|------|------|
| `check_flights.py` | Searches all three outbound dates, picks the cheapest |
| `.github/workflows/check-flights.yml` | Daily + manual GitHub Actions job |
| `data/` | Written on each run (`latest.json`, `history.jsonl`, `summary.md`) |
