#!/usr/bin/env python3
"""Check Barcelona hotel prices for pre/post cruise nights only.

Cruise nights July 15–24 are on the ship — not tracked.
Tracks:
  - Pre-embark:  2027-07-14 → 2027-07-15
  - Post-disembark: 2027-07-24 → 2027-07-25 (before return flight)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from stays import search_hotels

from mailer import send_email

CITY = "Barcelona"
CURRENCY = "CAD"
ADULTS = 2
EMAIL_TO = "bcw3bcw3@gmail.com"
ALERT_BELOW_CAD = 300.0  # total for the 1-night stay
PAUSE_SECONDS = 2
TOP_N = 5

# Nights outside the cruise only
HOTEL_STAYS = (
    {
        "id": "pre_cruise",
        "label": "Pre-cruise (before embark)",
        "check_in": "2027-07-14",
        "check_out": "2027-07-15",
        "note": "Arrive early for July 15 boarding — not mid-cruise",
    },
    {
        "id": "post_cruise",
        "label": "Post-cruise (before flight home)",
        "check_in": "2027-07-24",
        "check_out": "2027-07-25",
        "note": "Disembark July 24 → overnight before July 25 return flight",
    },
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_PATH = DATA_DIR / "hotel_history.jsonl"
LATEST_PATH = DATA_DIR / "hotel_latest.json"
SUMMARY_PATH = DATA_DIR / "hotel_summary.md"
ALERT_PATH = DATA_DIR / "hotel_alert.json"


def write_github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def normalize_hotel(raw: dict) -> dict:
    price = raw.get("display_price")
    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None
    return {
        "name": raw.get("name"),
        "price": price_f,
        "currency": raw.get("currency") or CURRENCY,
        "stars": raw.get("star_class"),
        "rating": raw.get("overall_rating"),
        "review_count": raw.get("review_count"),
        "entity_key": raw.get("entity_key"),
    }


def search_stay(stay: dict) -> dict:
    """Search Google Hotels for one stay window; return cheapest + top list."""
    check_in = stay["check_in"]
    check_out = stay["check_out"]
    try:
        res = search_hotels(
            query=CITY,
            check_in=check_in,
            check_out=check_out,
            adults=ADULTS,
            currency=CURRENCY,
            sort_by="LOWEST_PRICE",
            max_results=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            **stay,
            "found": False,
            "cheapest": None,
            "top": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    if not res.get("success"):
        return {
            **stay,
            "found": False,
            "cheapest": None,
            "top": [],
            "error": "search unsuccessful",
        }

    hotels = [normalize_hotel(h) for h in (res.get("hotels") or [])]
    priced = [h for h in hotels if h.get("price") is not None]
    # Prefer places with a guest rating when prices tie / filter junk
    priced.sort(
        key=lambda h: (
            float(h["price"]),
            -(h.get("rating") or 0),
        )
    )
    cheapest = priced[0] if priced else None
    return {
        **stay,
        "found": bool(cheapest),
        "cheapest": cheapest,
        "top": priced[:TOP_N],
        "error": None,
    }


def build_summary(run: dict) -> str:
    lines = [
        f"# Barcelona hotel check — {run['checked_at']}",
        "",
        "- City: **Barcelona**",
        "- Cruise nights **Jul 15–24 are excluded** (on the ship)",
        f"- Guests: {ADULTS} adults · Currency: {CURRENCY}",
        f"- Alert when cheapest 1-night total ≤ {CURRENCY} {ALERT_BELOW_CAD:,.0f}",
        "",
    ]
    for stay in run.get("stays") or []:
        lines.append(f"## {stay['label']}")
        lines.append("")
        lines.append(f"- Dates: **{stay['check_in']} → {stay['check_out']}**")
        if stay.get("note"):
            lines.append(f"- {stay['note']}")
        if stay.get("error"):
            lines.append(f"- Error: {stay['error']}")
        elif not stay.get("found"):
            lines.append("- No priced hotels found")
        else:
            c = stay["cheapest"]
            lines.append(
                f"- **Cheapest:** {c['currency']} {c['price']:,.0f} — {c['name']} "
                f"(★ {c.get('stars') or '—'}, rating {c.get('rating') or '—'})"
            )
            if stay.get("alert"):
                lines.append(
                    f"- **ALERT:** at or under {CURRENCY} {ALERT_BELOW_CAD:,.0f}"
                )
            lines.append("")
            lines.append("| Hotel | Price | Stars | Rating |")
            lines.append("|-------|------:|------:|-------:|")
            for h in stay.get("top") or []:
                lines.append(
                    f"| {h['name']} | {h['currency']} {h['price']:,.0f} | "
                    f"{h.get('stars') or '—'} | {h.get('rating') or '—'} |"
                )
        lines.append("")
    return "\n".join(lines)


def build_alert_payload(triggered: list[dict], checked_at: str) -> dict:
    titles = []
    email_lines = [
        "Barcelona hotel price alert",
        "",
        "Cruise nights Jul 15–24 are on the ship (not tracked).",
        f"Checked: {checked_at}",
        "",
    ]
    md_lines = [
        "Barcelona hotel price alert",
        "",
        "Cruise nights **Jul 15–24** are on the ship (not tracked).",
        f"Checked: **{checked_at}**",
        "",
    ]
    for t in triggered:
        c = t["cheapest"]
        titles.append(f"{t['label']}: {CURRENCY} {c['price']:,.0f}")
        email_lines.extend(
            [
                f"{t['label']} ({t['check_in']} → {t['check_out']})",
                f"  {CURRENCY} {c['price']:,.0f} — {c['name']}",
                f"  Threshold: {CURRENCY} {ALERT_BELOW_CAD:,.0f}",
                "",
            ]
        )
        md_lines.extend(
            [
                f"### {t['label']}",
                f"**{CURRENCY} {c['price']:,.0f}** — {c['name']}",
                f"- Dates: {t['check_in']} → {t['check_out']}",
                f"- Threshold: {CURRENCY} {ALERT_BELOW_CAD:,.0f}",
                "",
            ]
        )
    email_lines.append("Confirm on Google Hotels before booking.")
    md_lines.append("Confirm on Google Hotels before booking.")
    return {
        "alert": True,
        "triggered": triggered,
        "title": "Hotel alert: Barcelona " + " · ".join(titles),
        "body": "\n".join(md_lines),
        "email_body": "\n".join(email_lines),
    }


def main() -> int:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stays_out: list[dict] = []
    triggered: list[dict] = []
    errors = 0

    for i, stay in enumerate(HOTEL_STAYS):
        if i:
            time.sleep(PAUSE_SECONDS)
        result = search_stay(stay)
        alert = bool(
            result.get("found")
            and result.get("cheapest")
            and float(result["cheapest"]["price"]) <= ALERT_BELOW_CAD
        )
        result["alert"] = alert
        stays_out.append(result)
        status = (
            f"{CURRENCY} {result['cheapest']['price']:,.0f}"
            if result.get("found")
            else (result.get("error") or "no offers")
        )
        print(f"OK  {stay['id']}: {stay['check_in']} → {stay['check_out']}: {status}")
        if result.get("error"):
            errors += 1
        if alert:
            triggered.append(result)

    run = {
        "checked_at": checked_at,
        "city": CITY,
        "currency": CURRENCY,
        "adults": ADULTS,
        "alert_below_cad": ALERT_BELOW_CAD,
        "excluded": "Cruise nights 2027-07-15 through 2027-07-24 (on ship)",
        "stays": stays_out,
        "alert": bool(triggered),
        "triggered_alerts": [
            {
                "id": t["id"],
                "label": t["label"],
                "check_in": t["check_in"],
                "check_out": t["check_out"],
                "price": t["cheapest"]["price"],
                "hotel": t["cheapest"]["name"],
            }
            for t in triggered
        ],
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(run, indent=2) + "\n")
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(run) + "\n")

    if triggered:
        payload = build_alert_payload(triggered, checked_at)
        ALERT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        send_email(payload["title"], payload["email_body"], to_addr=EMAIL_TO)
    else:
        ALERT_PATH.write_text(json.dumps({"alert": False}) + "\n")

    write_github_output("hotel_alert", "true" if triggered else "false")
    summary = build_summary(run)
    SUMMARY_PATH.write_text(summary)
    print()
    print(summary)

    return 1 if errors == len(HOTEL_STAYS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
