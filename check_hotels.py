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
from datetime import date, datetime, timezone
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
# Per-night alert (CAD) for a 4★+ hotel
HOTEL_ALERT_BELOW_CAD = 200.0
MIN_STARS = 4
PAUSE_SECONDS = 2
TOP_N = 5

# Match flight landing options: hotel from landing until cruise embark Jul 15
LANDING_DATES = ("2027-07-09", "2027-07-10", "2027-07-11", "2027-07-12")
EMBARK_DATE = "2027-07-15"
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
    embark = date.fromisoformat(EMBARK_DATE)
    for landing in LANDING_DATES:
        check_in = date.fromisoformat(landing)
        windows.append(
            {
                "id": f"landing-{landing}",
                "label": f"Pre-cruise hotel (land {landing} → embark {EMBARK_DATE})",
                "kind": "landing",
                "flight_date": landing,
                "check_in": check_in.isoformat(),
                "check_out": embark.isoformat(),
                "nights": (embark - check_in).days,
            }
        )
    post_in = date.fromisoformat(POST_CRUISE[0])
    post_out = date.fromisoformat(POST_CRUISE[1])
    windows.append(
        {
            "id": "post-cruise",
            "label": "Post-cruise night (Jul 24→25)",
            "kind": "post_cruise",
            "flight_date": None,
            "check_in": POST_CRUISE[0],
            "check_out": POST_CRUISE[1],
            "nights": (post_out - post_in).days,
        }
    )
    return windows


def search_stay(check_in: str, check_out: str, nights: int) -> dict:
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
    empty = {
        "found": False,
        "price": None,
        "price_per_night": None,
        "nights": nights,
        "currency": CURRENCY,
        "name": None,
        "stars": None,
        "rating": None,
        "top": [],
        "note": None,
    }
    try:
        results = SearchHotels().search(filters)
    except Exception as exc:  # noqa: BLE001
        empty["note"] = f"{type(exc).__name__}: {exc}"
        return empty

    priced = []
    for h in results or []:
        price = getattr(h, "display_price", None)
        if price is None:
            continue
        total = float(price)
        per_night = total / nights if nights else total
        priced.append(
            {
                "name": getattr(h, "name", None),
                "price": total,
                "price_per_night": per_night,
                "currency": getattr(h, "currency", None) or CURRENCY,
                "stars": getattr(h, "star_class", None),
                "rating": getattr(h, "overall_rating", None),
                "review_count": getattr(h, "review_count", None),
            }
        )

    if not priced:
        empty["note"] = "No priced hotels (dates may be too far out, or blocked)"
        return empty

    priced.sort(key=lambda x: x["price_per_night"])
    best = priced[0]
    return {
        "found": True,
        "price": best["price"],
        "price_per_night": best["price_per_night"],
        "nights": nights,
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
        "- Tracked: land Jul 9–12 → embark Jul 15 + post-cruise Jul 24→25",
        "",
        "| Stay | Total | /night | Hotel | Stars |",
        "|------|------:|-------:|-------|------:|",
    ]
    for s in run["stays"]:
        if not s.get("found"):
            note = (s.get("note") or "no offers")[:40]
            lines.append(f"| {s['label']} | — | — | {note} | — |")
            continue
        name = (s.get("name") or "—")[:36]
        lines.append(
            f"| {s['label']} | {CURRENCY} {s['price']:,.0f} | "
            f"{CURRENCY} {s.get('price_per_night', s['price']):,.0f} | "
            f"{name} | {s.get('stars') or '—'} |"
        )
    lines.append("")
    triggered = run.get("triggered_alerts") or []
    if triggered:
        lines.append("## Alerts fired")
        lines.append("")
        for a in triggered:
            lines.append(
                f"- {a['label']}: {CURRENCY} {a['price_per_night']:,.0f}/night "
                f"(total {CURRENCY} {a['price']:,.0f}) — {a['name']}"
            )
        lines.append("")
    return "\n".join(lines)


def build_alert_payload(triggered: list[dict], checked_at: str) -> dict:
    titles = [
        f"{a['label'].split('(')[0].strip()} {CURRENCY} {a['price_per_night']:,.0f}/n"
        for a in triggered
    ]
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
                f"{a['label']}:",
                f"  {CURRENCY} {a['price_per_night']:,.2f}/night "
                f"(total {CURRENCY} {a['price']:,.2f} for {a['nights']} night(s))",
                f"  Hotel: {a['name']}",
                f"  Stars: {a.get('stars') or 'n/a'}",
                f"  Check-in {a['check_in']} → out {a['check_out']}",
                "",
            ]
        )
        md_lines.extend(
            [
                f"### {a['label']}",
                f"**{CURRENCY} {a['price_per_night']:,.2f}/night** "
                f"(total {CURRENCY} {a['price']:,.2f}, {a['nights']} night(s)) — {a['name']}",
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
        nights = int(window.get("nights") or 1)
        result = search_stay(window["check_in"], window["check_out"], nights)
        row = {**window, **result}
        stays_out.append(row)
        if result.get("found"):
            status = (
                f"{CURRENCY} {result['price_per_night']:,.0f}/n "
                f"(total {CURRENCY} {result['price']:,.0f}) — {result.get('name')}"
            )
        else:
            status = result.get("note") or "no offers"
        print(f"OK  {window['label']}: {status}")
        if result.get("note") and not result.get("found"):
            errors += 1
        per_night = result.get("price_per_night")
        if (
            result.get("found")
            and per_night is not None
            and float(per_night) <= HOTEL_ALERT_BELOW_CAD
        ):
            triggered.append(
                {
                    "label": window["label"],
                    "kind": window["kind"],
                    "check_in": window["check_in"],
                    "check_out": window["check_out"],
                    "nights": nights,
                    "price": result["price"],
                    "price_per_night": per_night,
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
            (
                s
                for s in stays_out
                if s.get("found") and s.get("price_per_night") is not None
            ),
            key=lambda s: s["price_per_night"],
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
