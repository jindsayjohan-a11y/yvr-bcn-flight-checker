# YVR → BCN flight price checker

Daily (and on-demand) price checks for:

| | |
|---|---|
| **From** | Vancouver (YVR) |
| **To** | Barcelona (BCN) |
| **Outbound** | 16, 17, or 18 July **2027** |
| **Return** | 25 July **2027** |

**Cost: $0.** No API keys, no accounts, no credit card. Prices come from Google Flights via the open-source [`fast-flights`](https://pypi.org/project/fast-flights/) library.

## Stay at $0 on GitHub

1. Prefer a **public** repo → Actions minutes are free.
2. Or keep it private and stay under **2,000 free minutes/month** (daily checks use ~30).
3. In GitHub: **Settings → Billing → Budgets** → set Actions budget to **$0** so nothing can ever charge.

## One-time setup

```bash
# from this folder
gh repo create yvr-bcn-flight-checker --public --source=. --remote=origin --push
```

Then: **Actions → Check flight prices → Run workflow**.

No secrets to add.

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
