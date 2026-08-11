#!/usr/bin/env python3
"""Check Barcelona hotel prices for flight-landing and post-cruise nights.

Cruise is July 15–24 (ship nights — not tracked).
Hotels needed when you land (tied to YVR→BCN flight dates) and the night
after disembarkation before the July 25 return flight.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from stays import (
    Currency,
    DateRange,
    GuestInfo,
    HotelSearchFilters,
    Location,
    PropertyType,
    SearchHotels,
    SortBy,
)

from mailer import send_email

CITY = "Barcelona"
CURRENCY = "CAD"
ADULTS = 1
EMAIL_TO = "bcw3bcw3@gmail.com"
# Per-night alert (CAD) for a 3★+ hotel
HOTEL_ALERT_BELOW_CAD = 200.0
MIN_STARS = 3
PAUSE_SECONDS = 2
TOP_N = 5

# Match flight landing options: need a hotel that night → checkout next day
LANDING_DATES = ("2027-07-16", "2027-07-17", "2027-07-18")
# After cruise (ends July 24) before return flight July 25
POST_CRUISE = ("2027-07-24", "2027-07-25")

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_PATH = DATA_DIR / "hotel_history.jsonl"
LATEST_PATH = DATA_DIR / "hotel_latest.json"
SUMMARY_PATH = DATA_DIR / "hotel_summary.md"
ALERT_PATH = DATA_DIR / "hotel_alert.json"


def stay_windows() -> list[dict]:
    windows = []
    for landing in LANDING_DATES:
        check_in = date.fromisoformat(landing)
        check_out = check_in + timedelta(days=1)
        windows.append(
            {
                "id": f"landing-{landing}",
                "label": f"Landing night ({landing})",
                "kind": "landing",
                "flight_date": landing,
                "check_in": check_in.isoformat(),
                "check_out": check_out.isoformat(),
            }
        )
    windows.append(
        {
            "id": "post-cruise",
            "label": "Post-cruise night (Jul 24→25)",
            "kind": "post_cruise",
            "flight_date": None,
            "check_in": POST_CRUISE[0],
            "check_out": POST_CRUISE[1],
        }
    )
    return windows


def search_stay(check_in: str, check_out: str) -> dict:
    filters = HotelSearchFilters(
        location=Location(query=CITY),
        dates=DateRange(
            check_in=date.fromisoformat(check_in),
            check_out=date.fromisoformat(check_out),
        ),
        guests=GuestInfo(adults=ADULTS),
        currency=Currency.CAD,
        property_type=PropertyType.HOTELS,
        sort_by=SortBy.LOWEST_PRICE,
        hotel_class=list(range(MIN_STARS, 6)),
    )
    try:
        results = SearchHotels().search(filters)
    except Exception as exc:  # noqa: BLE001
        return {
            "found": False,
            "price": None,
            "currency": CURRENCY,
            "name": None,
            "stars": None,
            "rating": None,
            "top": [],
            "note": f"{type(exc).__name__}: {exc}",
        }

    priced = []
    for h in results or []:
        price = getattr(h, "display_price", None)
        if price is None:
            continue
        priced.append(
            {
                "name": getattr(h, "name", None),
                "price": float(price),
                "currency": getattr(h, "currency", None) or CURRENCY,
                "stars": getattr(h, "star_class", None),
                "rating": getattr(h, "overall_rating", None),
                "review_count": getattr(h, "review_count", None),
            }
        )

    if not priced:
        return {
            "found": False,
            "price": None,
            "currency": CURRENCY,
            "name": None,
            "stars": None,
            "rating": None,
            "top": [],
            "note": "No priced hotels (dates may be too far out, or blocked)",
        }

    priced.sort(key=lambda x: x["price"])
    best = priced[0]
    return {
        "found": True,
        "price": best["price"],
        "currency": best["currency"],
        "name": best["name"],
        "stars": best["stars"],
        "rating": best["rating"],
        "top": priced[:TOP_N],
        "note": None,
    }


def write_github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def build_summary(run: dict) -> str:
    lines = [
        f"# Barcelona hotel check — {run['checked_at']}",
        "",
        "- City: **Barcelona**",
        f"- Guests: {ADULTS} adult(s), {MIN_STARS}★+",
        f"- Alert: ≤ **{CURRENCY} {HOTEL_ALERT_BELOW_CAD:,.0f}** / night",
        "- Cruise Jul 15–24 = ship (not tracked)",
        "- Tracked: landing nights (flight dates) + post-cruise Jul 24→25",
        "",
        "| Stay | Cheapest | Hotel | Stars |",
        "|------|--------:|-------|------:|",
    ]
    for s in run["stays"]:
        if not s.get("found"):
            note = (s.get("note") or "no offers")[:40]
            lines.append(f"| {s['label']} | — | {note} | — |")
            continue
        name = (s.get("name") or "—")[:40]
        lines.append(
            f"| {s['label']} | {CURRENCY} {s['price']:,.0f} | {name} | {s.get('stars') or '—'} |"
        )
    lines.append("")
    triggered = run.get("triggered_alerts") or []
    if triggered:
        lines.append("## Alerts fired")
        lines.append("")
        for a in triggered:
            lines.append(
                f"- {a['label']}: {CURRENCY} {a['price']:,.0f} — {a['name']}"
            )
        lines.append("")
    return "\n".join(lines)


def build_alert_payload(triggered: list[dict], checked_at: str) -> dict:
    titles = [f"{a['label']} {CURRENCY} {a['price']:,.0f}" for a in triggered]
    email_lines = [
        "Barcelona hotel price alert",
        "",
        f"Checked: {checked_at}",
        f"Threshold: {CURRENCY} {HOTEL_ALERT_BELOW_CAD:,.0f} / night ({MIN_STARS}★+)",
        "",
    ]
    md_lines = [
        f"Checked: **{checked_at}**",
        f"Threshold: **{CURRENCY} {HOTEL_ALERT_BELOW_CAD:,.0f}** / night ({MIN_STARS}★+)",
        "",
    ]
    for a in triggered:
        email_lines.extend(
            [
                f"{a['label']}: {CURRENCY} {a['price']:,.2f}",
                f"  Hotel: {a['name']}",
                f"  Stars: {a.get('stars') or 'n/a'}",
                f"  Check-in {a['check_in']} → out {a['check_out']}",
                "",
            ]
        )
        md_lines.extend(
            [
                f"### {a['label']}",
                f"**{CURRENCY} {a['price']:,.2f}** — {a['name']}",
                f"- Check-in {a['check_in']} → out {a['check_out']}",
                f"- Stars: {a.get('stars') or 'n/a'}",
                "",
            ]
        )
    email_lines.append("Confirm on Google Hotels before booking.")
    md_lines.append("Confirm on Google Hotels before booking.")
    return {
        "alert": True,
        "triggered": triggered,
        "title": "Hotel alert: BCN " + " · ".join(titles),
        "body": "\n".join(md_lines),
        "email_body": "\n".join(email_lines),
    }


def main() -> int:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stays_out: list[dict] = []
    triggered: list[dict] = []
    errors = 0

    for i, window in enumerate(stay_windows()):
        if i:
            time.sleep(PAUSE_SECONDS)
        result = search_stay(window["check_in"], window["check_out"])
        row = {**window, **result}
        stays_out.append(row)
        status = (
            f"{CURRENCY} {result['price']:,.0f} — {result.get('name')}"
            if result.get("found")
            else (result.get("note") or "no offers")
        )
        print(f"OK  {window['label']}: {status}")
        if result.get("note") and not result.get("found"):
            errors += 1
        if (
            result.get("found")
            and result.get("price") is not None
            and float(result["price"]) <= HOTEL_ALERT_BELOW_CAD
        ):
            triggered.append(
                {
                    "label": window["label"],
                    "kind": window["kind"],
                    "check_in": window["check_in"],
                    "check_out": window["check_out"],
                    "price": result["price"],
                    "name": result.get("name"),
                    "stars": result.get("stars"),
                    "threshold": HOTEL_ALERT_BELOW_CAD,
                }
            )

    run = {
        "checked_at": checked_at,
        "city": CITY,
        "currency": CURRENCY,
        "adults": ADULTS,
        "min_stars": MIN_STARS,
        "alert_below_cad": HOTEL_ALERT_BELOW_CAD,
        "stays": stays_out,
        "alert": bool(triggered),
        "triggered_alerts": triggered,
        "cheapest": min(
            (s for s in stays_out if s.get("found") and s.get("price") is not None),
            key=lambda s: s["price"],
            default=None,
        ),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(run, indent=2) + "\n")
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(run) + "\n")

    if triggered:
        alert_payload = build_alert_payload(triggered, checked_at)
        ALERT_PATH.write_text(json.dumps(alert_payload, indent=2) + "\n")
        send_email(
            alert_payload["title"],
            alert_payload["email_body"],
            to_addr=EMAIL_TO,
        )
    else:
        ALERT_PATH.write_text(json.dumps({"alert": False}) + "\n")

    write_github_output("hotel_alert", "true" if triggered else "false")
    summary = build_summary(run)
    SUMMARY_PATH.write_text(summary)
    print()
    print(summary)

    if errors == len(stays_out):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
