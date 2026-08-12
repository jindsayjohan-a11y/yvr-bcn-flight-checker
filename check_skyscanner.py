#!/usr/bin/env python3
"""Check YVR → BCN round-trip fares via Skyscanner (RapidAPI Sky Scrapper).

Runs once daily to stay within the free RapidAPI quota.
Same dates / cabin alert thresholds as Google Flights (`check_flights.py`).
Requires repo secret / env: RAPIDAPI_KEY
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mailer import send_email

ORIGIN = "YVR"
DESTINATION = "BCN"
OUTBOUND_DATES = ("2027-07-09", "2027-07-10", "2027-07-11", "2027-07-12")
RETURN_DATE = "2027-07-25"
ADULTS = 1
CURRENCY = "CAD"
MARKET = "en-CA"
COUNTRY_CODE = "CA"
EMAIL_TO = "bcw3bcw3@gmail.com"
PAUSE_SECONDS = 1.5

RAPIDAPI_HOST = "sky-scrapper.p.rapidapi.com"
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
# RapidAPI cabinClass values
CABIN_API: dict[Cabin, str] = {
    "economy": "economy",
    "premium-economy": "premium_economy",
    "business": "business",
}

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_PATH = DATA_DIR / "skyscanner_history.jsonl"
LATEST_PATH = DATA_DIR / "skyscanner_latest.json"
SUMMARY_PATH = DATA_DIR / "skyscanner_summary.md"
ALERT_PATH = DATA_DIR / "skyscanner_alert.json"


def api_get(path: str, params: dict[str, Any], api_key: str) -> dict:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    url = f"https://{RAPIDAPI_HOST}{path}?{query}"
    req = Request(
        url,
        headers={
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": RAPIDAPI_HOST,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc
    return json.loads(raw)


def resolve_airport(code: str, api_key: str) -> dict[str, str]:
    data = api_get(
        "/api/v1/flights/searchAirport",
        {"query": code, "locale": MARKET},
        api_key,
    )
    rows = data.get("data") or []
    code_u = code.upper()
    for row in rows:
        params = (row.get("navigation") or {}).get("relevantFlightParams") or {}
        sky = (params.get("skyId") or "").upper()
        if sky == code_u:
            return {
                "skyId": params["skyId"],
                "entityId": str(params["entityId"]),
                "title": ((row.get("presentation") or {}).get("title")) or code_u,
            }
    if not rows:
        raise RuntimeError(f"No Skyscanner airport match for {code}: {data}")
    params = (rows[0].get("navigation") or {}).get("relevantFlightParams") or {}
    return {
        "skyId": params["skyId"],
        "entityId": str(params["entityId"]),
        "title": ((rows[0].get("presentation") or {}).get("title")) or code,
    }


def extract_itineraries(payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    itineraries = data.get("itineraries")
    if isinstance(itineraries, list):
        return itineraries
    if isinstance(itineraries, dict):
        items: list[dict] = []
        for bucket in itineraries.get("buckets") or []:
            items.extend(bucket.get("items") or [])
        if items:
            return items
    # Some responses nest under flights
    flights = data.get("flights") or {}
    nested = flights.get("itineraries")
    if isinstance(nested, list):
        return nested
    return []


def itinerary_price(item: dict) -> float | None:
    price = item.get("price")
    if isinstance(price, dict):
        raw = price.get("raw")
        if raw is not None:
            return float(raw)
        amount = price.get("amount")
        if amount is not None:
            return float(amount)
    if isinstance(price, (int, float)):
        return float(price)
    return None


def itinerary_airlines(item: dict) -> list[str]:
    names: list[str] = []
    for leg in item.get("legs") or []:
        for carrier in leg.get("carriers", {}).get("marketing") or []:
            name = carrier.get("name")
            if name and name not in names:
                names.append(name)
        for seg in leg.get("segments") or []:
            op = seg.get("operatingCarrier") or seg.get("marketingCarrier") or {}
            name = op.get("name")
            if name and name not in names:
                names.append(name)
    return names


def itinerary_stops(item: dict) -> int | None:
    legs = item.get("legs") or []
    if not legs:
        return None
    stops = 0
    for leg in legs:
        if "stopCount" in leg:
            stops = max(stops, int(leg["stopCount"]))
        else:
            segs = leg.get("segments") or []
            if segs:
                stops = max(stops, max(len(segs) - 1, 0))
    return stops


def cheapest_for_date(
    outbound: str,
    cabin: Cabin,
    origin: dict[str, str],
    destination: dict[str, str],
    api_key: str,
) -> dict:
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
        "source": "skyscanner",
    }
    try:
        payload = api_get(
            "/api/v2/flights/searchFlights",
            {
                "originSkyId": origin["skyId"],
                "destinationSkyId": destination["skyId"],
                "originEntityId": origin["entityId"],
                "destinationEntityId": destination["entityId"],
                "date": outbound,
                "returnDate": RETURN_DATE,
                "cabinClass": CABIN_API[cabin],
                "adults": ADULTS,
                "sortBy": "best",
                "currency": CURRENCY,
                "market": MARKET,
                "countryCode": COUNTRY_CODE,
            },
            api_key,
        )
    except Exception as exc:  # noqa: BLE001
        base["note"] = f"{type(exc).__name__}: {exc}"
        return base

    priced = []
    for item in extract_itineraries(payload):
        price = itinerary_price(item)
        if price is None:
            continue
        priced.append(
            {
                "price": price,
                "airlines": itinerary_airlines(item),
                "stops_approx": itinerary_stops(item),
            }
        )

    if not priced:
        status = payload.get("status") or payload.get("message")
        base["note"] = (
            f"No priced itineraries"
            + (f" ({status})" if status else "")
            + " — dates may be too far out, or quota/API limited"
        )
        return base

    best = min(priced, key=lambda x: x["price"])
    base.update(
        {
            "found": True,
            "price": float(best["price"]),
            "airlines": best["airlines"],
            "stops_approx": best["stops_approx"],
        }
    )
    return base


def format_money(price: float | None, currency: str = CURRENCY) -> str:
    if price is None:
        return "—"
    return f"{currency} {price:,.2f}"


def build_summary(run: dict) -> str:
    lines = [
        f"# YVR → BCN Skyscanner check — {run['checked_at']}",
        "",
        f"- Route: **{ORIGIN} → {DESTINATION}** (round trip)",
        f"- Return: **{RETURN_DATE}**",
        "- Source: **Skyscanner** via RapidAPI Sky Scrapper (daily)",
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
                lines.append(f"- **ALERT:** at or under {CURRENCY} {threshold:,.0f}")
            else:
                lines.append(f"- Threshold not met ({CURRENCY} {threshold:,.0f})")
        else:
            lines.append(f"No priced {label.lower()} offers yet.")
        lines.append("")
    return "\n".join(lines)


def write_github_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def build_alert_payload(triggered: list[dict], checked_at: str) -> dict:
    titles = [f"{a['cabin_label']} {CURRENCY} {a['price']:,.0f}" for a in triggered]
    body_parts = [
        "YVR → BCN Skyscanner price alert",
        "",
        f"Checked: {checked_at}",
        f"Return: {RETURN_DATE}",
        "Source: Skyscanner (RapidAPI)",
        "",
    ]
    md_parts = [
        f"Checked: **{checked_at}**",
        f"Return: **{RETURN_DATE}**",
        "Source: **Skyscanner**",
        "",
    ]
    for a in triggered:
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
                f"**{CURRENCY} {a['price']:,.2f}** (≤ {CURRENCY} {a['threshold']:,.0f})",
                f"- Outbound: {a['outbound']}",
                f"- Airlines: {a['airlines']}",
                "",
            ]
        )
    body_parts.extend(
        [
            "Confirm on Skyscanner before booking:",
            "https://www.skyscanner.ca/",
            "",
        ]
    )
    md_parts.append("Confirm on [Skyscanner](https://www.skyscanner.ca/) before booking.")
    return {
        "alert": True,
        "triggered": triggered,
        "checked_at": checked_at,
        "title": "Skyscanner alert: YVR→BCN " + " · ".join(titles),
        "body": "\n".join(md_parts),
        "email_body": "\n".join(body_parts),
    }


def main() -> int:
    api_key = (os.environ.get("RAPIDAPI_KEY") or "").strip()
    if not api_key:
        print(
            "RAPIDAPI_KEY not set — skipping Skyscanner check.\n"
            "Add a RapidAPI key for sky-scrapper as repo secret RAPIDAPI_KEY.",
            file=sys.stderr,
        )
        write_github_output("skyscanner_alert", "false")
        write_github_output("skyscanner_skipped", "true")
        return 0

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        origin = resolve_airport(ORIGIN, api_key)
        time.sleep(PAUSE_SECONDS)
        destination = resolve_airport(DESTINATION, api_key)
        print(f"Airports: {origin['title']} → {destination['title']}")
    except Exception as exc:  # noqa: BLE001
        print(f"Airport lookup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        write_github_output("skyscanner_alert", "false")
        return 1

    cabins_out: dict[str, dict] = {}
    errors: list[str] = []
    triggered: list[dict] = []
    search_count = 0

    for cabin in CABINS:
        results: list[dict] = []
        for outbound in OUTBOUND_DATES:
            time.sleep(PAUSE_SECONDS)
            search_count += 1
            try:
                row = cheapest_for_date(outbound, cabin, origin, destination, api_key)
                results.append(row)
                status = (
                    f"{row['currency']} {row['price']:,.2f}"
                    if row.get("found")
                    else "no offers"
                )
                print(f"OK  skyscanner {cabin:17} {outbound} → {RETURN_DATE}: {status}")
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
                        "source": "skyscanner",
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
                    "source": "skyscanner",
                }
            )

    run = {
        "checked_at": checked_at,
        "origin": ORIGIN,
        "destination": DESTINATION,
        "return_date": RETURN_DATE,
        "outbound_dates": list(OUTBOUND_DATES),
        "currency": CURRENCY,
        "source": "skyscanner_rapidapi",
        "alert_thresholds": dict(ALERT_BELOW_CAD),
        "cabins": cabins_out,
        "cheapest": (cabins_out.get("economy") or {}).get("cheapest"),
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
        send_email(
            alert_payload["title"],
            alert_payload.get("email_body") or alert_payload["body"],
            to_addr=EMAIL_TO,
        )
    else:
        ALERT_PATH.write_text(json.dumps({"alert": False}) + "\n")

    write_github_output("skyscanner_alert", "true" if triggered else "false")
    write_github_output("skyscanner_skipped", "false")
    summary = build_summary(run)
    SUMMARY_PATH.write_text(summary)
    print()
    print(summary)

    total = len(CABINS) * len(OUTBOUND_DATES)
    if errors and len(errors) == total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
