# YVR → BCN flight price checker

Daily (and on-demand) price checks for:

| | |
|---|---|
| **From** | Vancouver (YVR) |
| **To** | Barcelona (BCN) |
| **Outbound** | 16, 17, or 18 July **2027** |
| **Return** | 25 July **2027** |

**Cost: $0.** Prices come from Google Flights via [`fast-flights`](https://pypi.org/project/fast-flights/). Optional Telegram alerts use a free bot (no credit card).

## Stay at $0 on GitHub

1. Prefer a **public** repo → Actions minutes are free.
2. Or keep it private and stay under **2,000 free minutes/month** (daily checks use ~30).
3. In GitHub: **Settings → Billing → Budgets** → set Actions budget to **$0** so nothing can ever charge.

## One-time setup

Repo is already live. To enable Telegram alerts, add two secrets (below).

## Price alerts (≤ CAD 1100)

When the cheapest round-trip is **at or under CAD 1,100**:

1. **Telegram** message (if secrets are set)
2. GitHub **Issue** labeled `price-alert` (email if you Watch the repo)

### Telegram setup (free, ~2 minutes)

1. In Telegram, open [@BotFather](https://t.me/BotFather) → `/newbot` → follow prompts → copy the **bot token**
2. Open your new bot and tap **Start** (send any message)
3. In a browser, open (paste your token):
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id": 123456789` — that number is your **chat id**
5. In the GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**
   - `TELEGRAM_BOT_TOKEN` = bot token
   - `TELEGRAM_CHAT_ID` = chat id

Optional email: repo → **Watch** → **Custom** → **Issues**.

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
