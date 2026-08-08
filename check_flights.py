#!/usr/bin/env python3
"""Check round-trip flight prices: YVR → BCN for July 2027.

Uses Google Flights via the open-source `fast-flights` library.
No API keys, no accounts, no credit card.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fast_flights import FlightQuery, Passengers, create_filter, get_flights
from fast_flights.exceptions import FlightsNotFound

ORIGIN = "YVR"
DESTINATION = "BCN"
OUTBOUND_DATES = ("2027-07-16", "2027-07-17", "2027-07-18")
RETURN_DATE = "2027-07-25"
ADULTS = 1
CURRENCY = "CAD"
ALERT_BELOW_CAD = 1100.0  # notify when cheapest round-trip is at/under this
PAUSE_SECONDS = 2  # be polite between date searches

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_PATH = DATA_DIR / "history.jsonl"
LATEST_PATH = DATA_DIR / "latest.json"
SUMMARY_PATH = DATA_DIR / "summary.md"
ALERT_PATH = DATA_DIR / "alert.json"


def cheapest_for_date(outbound: str) -> dict:
    """Return cheapest Google Flights offer for one outbound + fixed return."""
    query = create_filter(
        flights=[
            FlightQuery(date=outbound, from_airport=ORIGIN, to_airport=DESTINATION),
            FlightQuery(date=RETURN_DATE, from_airport=DESTINATION, to_airport=ORIGIN),
        ],
        trip="round-trip",
        seat="economy",
        passengers=Passengers(adults=ADULTS),
        currency=CURRENCY,
    )

    try:
        results = get_flights(query)
    except FlightsNotFound:
        return {
            "outbound": outbound,
            "return": RETURN_DATE,
            "found": False,
            "price": None,
            "currency": CURRENCY,
            "airlines": None,
            "note": "No offers (Google may not publish this far ahead yet, or blocked this IP)",
        }

    priced = [f for f in results if getattr(f, "price", None) is not None]
    if not priced:
        return {
            "outbound": outbound,
            "return": RETURN_DATE,
            "found": False,
            "price": None,
            "currency": CURRENCY,
            "airlines": None,
            "note": "Results returned but no prices",
        }

    best = min(priced, key=lambda f: float(f.price))
    airlines = list(getattr(best, "airlines", None) or [])
    legs = getattr(best, "flights", None) or []
    stops = max(len(legs) - 1, 0) if legs else None

    return {
        "outbound": outbound,
        "return": RETURN_DATE,
        "found": True,
        "price": float(best.price),
        "currency": CURRENCY,
        "airlines": airlines,
        "stops_approx": stops,
        "note": None,
    }


def format_money(price: float | None, currency: str) -> str:
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
        "## Results by outbound date",
        "",
        "| Outbound | Price | Airlines | Note |",
        "|----------|------:|----------|------|",
    ]
    for r in run["results"]:
        if not r["found"]:
            note = (r.get("note") or "no offers")[:60]
            lines.append(f"| {r['outbound']} | — | — | {note} |")
            continue
        airlines = ", ".join(r.get("airlines") or []) or "—"
        lines.append(
            f"| {r['outbound']} | {format_money(r['price'], r['currency'])} "
            f"| {airlines} | |"
        )

    best = run.get("cheapest")
    lines.extend(["", "## Cheapest overall", ""])
    if best and best.get("found"):
        airlines = ", ".join(best.get("airlines") or []) or "airline n/a"
        lines.append(
            f"**{format_money(best['price'], best['currency'])}** — "
            f"depart {best['outbound']}, return {best['return']} ({airlines})"
        )
        prev = run.get("previous_cheapest")
        if prev and prev.get("price") is not None:
            delta = best["price"] - prev["price"]
            arrow = "↓" if delta < 0 else ("↑" if delta > 0 else "→")
            lines.append(
                f"- vs last run: {arrow} {format_money(abs(delta), best['currency'])} "
                f"(was {format_money(prev['price'], prev.get('currency', best['currency']))})"
            )
        threshold = run.get("alert_below_cad", ALERT_BELOW_CAD)
        if run.get("alert"):
            lines.append(
                f"- **ALERT:** at or under {CURRENCY} {threshold:,.0f} — GitHub Issue notification fired"
            )
        else:
            lines.append(f"- Alert threshold: {CURRENCY} {threshold:,.0f} (not met)")
    else:
        lines.append(
            "No priced offers yet. July 2027 may still be outside airline publish windows — "
            "keep the daily check running and prices should appear later."
        )

    lines.append("")
    return "\n".join(lines)


def load_previous_cheapest() -> dict | None:
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
    return last.get("cheapest")


def write_github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def main() -> int:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    results: list[dict] = []
    errors: list[str] = []

    for i, outbound in enumerate(OUTBOUND_DATES):
        if i:
            time.sleep(PAUSE_SECONDS)
        try:
            row = cheapest_for_date(outbound)
            results.append(row)
            status = (
                f"{row['currency']} {row['price']:,.2f}" if row.get("found") else "no offers"
            )
            print(f"OK  {outbound} → {RETURN_DATE}: {status}")
        except Exception as exc:  # noqa: BLE001 — log and continue other dates
            msg = f"{outbound}: {type(exc).__name__}: {exc}"
            errors.append(msg)
            print(msg, file=sys.stderr)
            results.append(
                {
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
    previous = load_previous_cheapest()
    alert = bool(
        cheapest and cheapest.get("found") and float(cheapest["price"]) <= ALERT_BELOW_CAD
    )

    run = {
        "checked_at": checked_at,
        "origin": ORIGIN,
        "destination": DESTINATION,
        "return_date": RETURN_DATE,
        "outbound_dates": list(OUTBOUND_DATES),
        "currency": CURRENCY,
        "source": "google_flights_fast_flights",
        "alert_below_cad": ALERT_BELOW_CAD,
        "alert": alert,
        "results": results,
        "cheapest": cheapest,
        "previous_cheapest": previous,
        "errors": errors,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(json.dumps(run, indent=2) + "\n")
    with HISTORY_PATH.open("a") as f:
        f.write(json.dumps(run) + "\n")

    if alert and cheapest:
        airlines = ", ".join(cheapest.get("airlines") or []) or "n/a"
        alert_payload = {
            "alert": True,
            "price": cheapest["price"],
            "currency": cheapest.get("currency", CURRENCY),
            "outbound": cheapest["outbound"],
            "return": cheapest["return"],
            "airlines": airlines,
            "threshold": ALERT_BELOW_CAD,
            "checked_at": checked_at,
            "title": (
                f"Price alert: YVR→BCN {CURRENCY} {cheapest['price']:,.0f} "
                f"(at/under {ALERT_BELOW_CAD:,.0f})"
            ),
            "body": (
                f"Cheapest round-trip is **{CURRENCY} {cheapest['price']:,.2f}** "
                f"(threshold {CURRENCY} {ALERT_BELOW_CAD:,.0f}).\n\n"
                f"- Outbound: {cheapest['outbound']}\n"
                f"- Return: {cheapest['return']}\n"
                f"- Airlines: {airlines}\n"
                f"- Checked: {checked_at}\n\n"
                f"Confirm on [Google Flights](https://www.google.com/travel/flights) before booking."
            ),
        }
        ALERT_PATH.write_text(json.dumps(alert_payload, indent=2) + "\n")
    else:
        ALERT_PATH.write_text(json.dumps({"alert": False}) + "\n")

    write_github_output("alert", "true" if alert else "false")
    if cheapest and cheapest.get("price") is not None:
        write_github_output("price", f"{cheapest['price']:.2f}")
    else:
        write_github_output("price", "")

    summary = build_summary(run)
    SUMMARY_PATH.write_text(summary)
    print()
    print(summary)

    # Exit 0 even when no fares yet (common for far-out dates).
    # Exit 1 only if every date threw an unexpected error.
    if errors and not found and len(errors) == len(OUTBOUND_DATES):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
