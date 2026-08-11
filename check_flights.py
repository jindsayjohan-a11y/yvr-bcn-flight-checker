#!/usr/bin/env python3
"""Check round-trip flight prices: YVR → BCN for July 2027.

Uses Google Flights via the open-source `fast-flights` library.
Alerts by cabin: economy, premium economy, business.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fast_flights import FlightQuery, Passengers, create_filter, get_flights
from fast_flights.exceptions import FlightsNotFound

from mailer import send_email

ORIGIN = "YVR"
DESTINATION = "BCN"
OUTBOUND_DATES = ("2027-07-09", "2027-07-10", "2027-07-11", "2027-07-12")
RETURN_DATE = "2027-07-25"
ADULTS = 1
CURRENCY = "CAD"
EMAIL_TO = "bcw3bcw3@gmail.com"
PAUSE_SECONDS = 2

Cabin = Literal["economy", "premium-economy", "business"]

CABINS: tuple[Cabin, ...] = ("economy", "premium-economy", "business")
ALERT_BELOW_CAD: dict[Cabin, float] = {
    "economy": 1100.0,
    "premium-economy": 1600.0,
    "business": 2500.0,
}
CABIN_LABELS: dict[Cabin, str] = {
    "economy": "Economy",
    "premium-economy": "Premium economy",
    "business": "Business",
}

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_PATH = DATA_DIR / "history.jsonl"
LATEST_PATH = DATA_DIR / "latest.json"
SUMMARY_PATH = DATA_DIR / "summary.md"
ALERT_PATH = DATA_DIR / "alert.json"


def cheapest_for_date(outbound: str, cabin: Cabin) -> dict:
    """Return cheapest Google Flights offer for one outbound + cabin."""
    query = create_filter(
        flights=[
            FlightQuery(date=outbound, from_airport=ORIGIN, to_airport=DESTINATION),
            FlightQuery(date=RETURN_DATE, from_airport=DESTINATION, to_airport=ORIGIN),
        ],
        trip="round-trip",
        seat=cabin,
        passengers=Passengers(adults=ADULTS),
        currency=CURRENCY,
    )

    base = {
        "cabin": cabin,
        "outbound": outbound,
        "return": RETURN_DATE,
        "found": False,
        "price": None,
        "currency": CURRENCY,
        "airlines": None,
        "stops_approx": None,
        "note": None,
    }

    try:
        results = get_flights(query)
    except FlightsNotFound:
        base["note"] = (
            "No offers (Google may not publish this far ahead yet, or blocked this IP)"
        )
        return base

    priced = [f for f in results if getattr(f, "price", None) is not None]
    if not priced:
        base["note"] = "Results returned but no prices"
        return base

    best = min(priced, key=lambda f: float(f.price))
    airlines = list(getattr(best, "airlines", None) or [])
    legs = getattr(best, "flights", None) or []
    stops = max(len(legs) - 1, 0) if legs else None

    base.update(
        {
            "found": True,
            "price": float(best.price),
            "airlines": airlines,
            "stops_approx": stops,
        }
    )
    return base


def format_money(price: float | None, currency: str = CURRENCY) -> str:
    if price is None:
        return "—"
    return f"{currency} {price:,.2f}"


def build_summary(run: dict) -> str:
    lines = [
        f"# YVR → BCN flight check — {run['checked_at']}",
        "",
        f"- Route: **{ORIGIN} → {DESTINATION}** (round trip)",
        f"- Return: **{RETURN_DATE}**",
        f"- Source: Google Flights (no API key)",
        f"- Adults: {ADULTS}",
        "",
    ]

    for cabin in CABINS:
        label = CABIN_LABELS[cabin]
        threshold = ALERT_BELOW_CAD[cabin]
        block = (run.get("cabins") or {}).get(cabin) or {}
        cheapest = block.get("cheapest")
        lines.append(f"## {label} (alert ≤ {CURRENCY} {threshold:,.0f})")
        lines.append("")
        lines.append("| Outbound | Price | Airlines | Note |")
        lines.append("|----------|------:|----------|------|")
        for r in block.get("results") or []:
            if not r.get("found"):
                note = (r.get("note") or "no offers")[:60]
                lines.append(f"| {r['outbound']} | — | — | {note} |")
                continue
            airlines = ", ".join(r.get("airlines") or []) or "—"
            lines.append(
                f"| {r['outbound']} | {format_money(r['price'], r['currency'])} "
                f"| {airlines} | |"
            )
        lines.append("")
        if cheapest and cheapest.get("found"):
            airlines = ", ".join(cheapest.get("airlines") or []) or "airline n/a"
            lines.append(
                f"**Cheapest {label.lower()}:** {format_money(cheapest['price'])} — "
                f"depart {cheapest['outbound']} ({airlines})"
            )
            if block.get("alert"):
                lines.append(
                    f"- **ALERT:** at or under {CURRENCY} {threshold:,.0f}"
                )
            else:
                lines.append(f"- Threshold not met ({CURRENCY} {threshold:,.0f})")
        else:
            lines.append(f"No priced {label.lower()} offers yet.")
        lines.append("")

    triggered = run.get("triggered_alerts") or []
    if triggered:
        lines.append("## Alerts fired")
        lines.append("")
        for a in triggered:
            lines.append(
                f"- {a['cabin_label']}: {format_money(a['price'])} "
                f"(≤ {CURRENCY} {a['threshold']:,.0f})"
            )
        lines.append("")

    return "\n".join(lines)


def load_previous_cheapest_economy() -> dict | None:
    if not HISTORY_PATH.exists():
        return None
    last = None
    with HISTORY_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    if not last:
        return None
    cabins = last.get("cabins") or {}
    if "economy" in cabins:
        return (cabins["economy"] or {}).get("cheapest")
    return last.get("cheapest")


def write_github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def build_alert_payload(triggered: list[dict], checked_at: str) -> dict:
    titles = []
    body_parts = [
        "YVR → BCN price alert",
        "",
        f"Checked: {checked_at}",
        f"Return: {RETURN_DATE}",
        "",
    ]
    md_parts = [
        f"Checked: **{checked_at}**",
        f"Return: **{RETURN_DATE}**",
        "",
    ]

    for a in triggered:
        titles.append(
            f"{a['cabin_label']} {CURRENCY} {a['price']:,.0f}"
        )
        body_parts.extend(
            [
                f"{a['cabin_label']}: {CURRENCY} {a['price']:,.2f} "
                f"(threshold {CURRENCY} {a['threshold']:,.0f})",
                f"  Outbound: {a['outbound']}",
                f"  Airlines: {a['airlines']}",
                "",
            ]
        )
        md_parts.extend(
            [
                f"### {a['cabin_label']}",
                f"**{CURRENCY} {a['price']:,.2f}** "
                f"(≤ {CURRENCY} {a['threshold']:,.0f})",
                f"- Outbound: {a['outbound']}",
                f"- Airlines: {a['airlines']}",
                "",
            ]
        )

    body_parts.extend(
        [
            "Confirm on Google Flights before booking:",
            "https://www.google.com/travel/flights",
            "",
        ]
    )
    md_parts.append(
        "Confirm on [Google Flights](https://www.google.com/travel/flights) before booking."
    )

    title = "Price alert: YVR→BCN " + " · ".join(titles)
    return {
        "alert": True,
        "triggered": triggered,
        "checked_at": checked_at,
        "title": title,
        "body": "\n".join(md_parts),
        "email_body": "\n".join(body_parts),
    }


def send_email_alert(alert_payload: dict) -> bool:
    return send_email(
        alert_payload["title"],
        alert_payload.get("email_body") or alert_payload["body"],
        to_addr=EMAIL_TO,
    )


def main() -> int:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cabins_out: dict[str, dict] = {}
    errors: list[str] = []
    triggered: list[dict] = []
    search_count = 0

    for cabin in CABINS:
        results: list[dict] = []
        for outbound in OUTBOUND_DATES:
            if search_count:
                time.sleep(PAUSE_SECONDS)
            search_count += 1
            try:
                row = cheapest_for_date(outbound, cabin)
                results.append(row)
                status = (
                    f"{row['currency']} {row['price']:,.2f}"
                    if row.get("found")
                    else "no offers"
                )
                print(f"OK  {cabin:17} {outbound} → {RETURN_DATE}: {status}")
            except Exception as exc:  # noqa: BLE001
                msg = f"{cabin}/{outbound}: {type(exc).__name__}: {exc}"
                errors.append(msg)
                print(msg, file=sys.stderr)
                results.append(
                    {
                        "cabin": cabin,
                        "outbound": outbound,
                        "return": RETURN_DATE,
                        "found": False,
                        "price": None,
                        "currency": CURRENCY,
                        "airlines": None,
                        "note": msg,
                    }
                )

        found = [r for r in results if r.get("found") and r.get("price") is not None]
        cheapest = min(found, key=lambda r: r["price"]) if found else None
        threshold = ALERT_BELOW_CAD[cabin]
        alert = bool(
            cheapest and cheapest.get("found") and float(cheapest["price"]) <= threshold
        )
        cabins_out[cabin] = {
            "threshold": threshold,
            "results": results,
            "cheapest": cheapest,
            "alert": alert,
        }
        if alert and cheapest:
            airlines = ", ".join(cheapest.get("airlines") or []) or "n/a"
            triggered.append(
                {
                    "cabin": cabin,
                    "cabin_label": CABIN_LABELS[cabin],
                    "price": cheapest["price"],
                    "currency": CURRENCY,
                    "threshold": threshold,
                    "outbound": cheapest["outbound"],
                    "return": RETURN_DATE,
                    "airlines": airlines,
                }
            )

    economy_cheapest = (cabins_out.get("economy") or {}).get("cheapest")
    previous = load_previous_cheapest_economy()

    run = {
        "checked_at": checked_at,
        "origin": ORIGIN,
        "destination": DESTINATION,
        "return_date": RETURN_DATE,
        "outbound_dates": list(OUTBOUND_DATES),
        "currency": CURRENCY,
        "source": "google_flights_fast_flights",
        "alert_thresholds": dict(ALERT_BELOW_CAD),
        "cabins": cabins_out,
        # Backward-compatible fields for biweekly summary
        "cheapest": economy_cheapest,
        "previous_cheapest": previous,
        "alert": bool(triggered),
        "triggered_alerts": triggered,
        "errors": errors,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(run, indent=2) + "\n")
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(run) + "\n")

    if triggered:
        alert_payload = build_alert_payload(triggered, checked_at)
        ALERT_PATH.write_text(json.dumps(alert_payload, indent=2) + "\n")
        send_email_alert(alert_payload)
    else:
        ALERT_PATH.write_text(json.dumps({"alert": False}) + "\n")

    write_github_output("alert", "true" if triggered else "false")
    if economy_cheapest and economy_cheapest.get("price") is not None:
        write_github_output("price", f"{economy_cheapest['price']:.2f}")
    else:
        write_github_output("price", "")

    summary = build_summary(run)
    SUMMARY_PATH.write_text(summary)
    print()
    print(summary)

    total_searches = len(CABINS) * len(OUTBOUND_DATES)
    if errors and len(errors) == total_searches:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
