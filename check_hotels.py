#!/usr/bin/env python3
"""Check Barcelona hotel prices for pre/post cruise nights only.

Cruise is July 15–24 (ship nights — not tracked).
Tracks only:
  - Pre-embark: 2027-07-11 → 2027-07-15
  - Post-disembark: 2027-07-24 → 2027-07-25 (before return flight)
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from stays import (
    Brand,
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

# Tourist-center search (Gothic / Ramblas / Plaça Catalunya area)
CITY_QUERY = "Plaça de Catalunya Barcelona"
# Plaça de Catalunya — classic first-timer hub
CENTER_LAT = 41.3870
CENTER_LON = 2.1701
MAX_KM_FROM_CENTER = 4.0

CURRENCY = "CAD"
ADULTS = 1
EMAIL_TO = "bcw3bcw3@gmail.com"
# Per-night alert (CAD) for a 3★+ major-chain hotel (Google uses whole stars;
# 3★ includes typical 3.5★ midscale like Hampton / Holiday Inn Express)
HOTEL_ALERT_BELOW_CAD = 200.0
MIN_STARS = 3
# Google Hotels brand chips — major reputable chains only
CHAIN_BRANDS = [
    Brand.MARRIOTT,
    Brand.HYATT,
    Brand.ACCOR,
    Brand.HILTON,
    Brand.IHG,
    Brand.FOUR_SEASONS,
]
# Far-out dates often return one fake total for almost every hotel (unbookable).
PLACEHOLDER_SAME_PRICE_RATIO = 0.5
# Multi-night Google list prices often don't scale with nights; treat as nightly.
# Require real OTA rate plans (Booking/Expedia/etc.) before alerting.
REQUIRE_OTA_RATES_FOR_ALERT = True
OTA_VERIFY_CANDIDATES = 5
PAUSE_SECONDS = 2
TOP_N = 5

# Outside the cruise only (ship nights Jul 15–24 excluded)
PRE_CRUISE = ("2027-07-11", "2027-07-15")  # land Jul 11 → embark Jul 15
POST_CRUISE = ("2027-07-24", "2027-07-25")  # after disembark, before Jul 25 flight

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HISTORY_PATH = DATA_DIR / "hotel_history.jsonl"
LATEST_PATH = DATA_DIR / "hotel_latest.json"
SUMMARY_PATH = DATA_DIR / "hotel_summary.md"
ALERT_PATH = DATA_DIR / "hotel_alert.json"

# Known Accor property codes (optional direct book links)
ACCOR_HOTEL_CODES = {
    "mercure barcelona condor": "9267",
}


def stay_windows() -> list[dict]:
    windows = []
    for stay_id, label, kind, pair in (
        (
            "pre-cruise",
            "Pre-cruise hotel (Jul 11→15)",
            "pre_cruise",
            PRE_CRUISE,
        ),
        (
            "post-cruise",
            "Post-cruise night (Jul 24→25)",
            "post_cruise",
            POST_CRUISE,
        ),
    ):
        check_in = date.fromisoformat(pair[0])
        check_out = date.fromisoformat(pair[1])
        windows.append(
            {
                "id": stay_id,
                "label": label,
                "kind": kind,
                "check_in": pair[0],
                "check_out": pair[1],
                "nights": (check_out - check_in).days,
            }
        )
    return windows


def km_from_center(lat: float | None, lon: float | None) -> float | None:
    if lat is None or lon is None:
        return None
    r = 6371.0
    la1, lo1 = math.radians(CENTER_LAT), math.radians(CENTER_LON)
    la2, lo2 = math.radians(lat), math.radians(lon)
    dlat, dlon = la2 - la1, lo2 - lo1
    a = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def prices_look_like_placeholders(priced: list[dict]) -> bool:
    """Google often shows one fake total for nearly every hotel when dates aren't open yet."""
    if len(priced) < 3:
        return False
    counts = Counter(round(float(p["price"]), 2) for p in priced)
    _top_price, top_n = counts.most_common(1)[0]
    return (top_n / len(priced)) >= PLACEHOLDER_SAME_PRICE_RATIO


def booking_links(
    name: str | None,
    check_in: str,
    check_out: str,
    *,
    entity_key: str | None = None,
    nights: int = 1,
    ota_url: str | None = None,
    ota_provider: str | None = None,
) -> dict[str, str]:
    """Deep links that open the hotel with the alert dates pre-filled."""
    hotel = (name or "").strip() or "Barcelona hotel"
    links: dict[str, str] = {}
    if ota_url:
        key = "ota"
        links[key] = ota_url
        if ota_provider:
            links["ota_provider"] = ota_provider
    if entity_key:
        links["google_hotels"] = (
            "https://www.google.com/travel/hotels/entity/"
            + entity_key
            + "?"
            + urlencode(
                {
                    "dates": f"{check_in},{check_out}",
                    "adults": ADULTS,
                    "curr": CURRENCY,
                    "hl": "en-CA",
                    "gl": "ca",
                }
            )
        )
    links["booking_com"] = (
        "https://www.booking.com/searchresults.html?"
        + urlencode(
            {
                "ss": hotel,
                "checkin": check_in,
                "checkout": check_out,
                "group_adults": ADULTS,
                "no_rooms": 1,
                "selected_currency": CURRENCY,
            }
        )
    )
    accor_code = ACCOR_HOTEL_CODES.get(hotel.casefold())
    if accor_code:
        links["accor"] = (
            f"https://all.accor.com/booking/en/hotel/{accor_code}?"
            + urlencode(
                {
                    "dateIn": check_in,
                    "nights": max(int(nights), 1),
                    "compositions": ADULTS,
                    "stayplus": "false",
                }
            )
        )
    return links


def extract_ota_rates(detail) -> list[dict]:
    """Return bookable OTA rate plans with deeplinks from a HotelDetail."""
    rates: list[dict] = []
    for room in getattr(detail, "rooms", None) or []:
        for plan in getattr(room, "rates", None) or []:
            price = getattr(plan, "price", None)
            url = getattr(plan, "deeplink_url", None)
            if price is None or not url:
                continue
            rates.append(
                {
                    "price": float(price),
                    "currency": getattr(plan, "currency", None) or CURRENCY,
                    "provider": getattr(plan, "provider", None) or "OTA",
                    "url": url,
                    "room": getattr(room, "name", None),
                }
            )
    rates.sort(key=lambda r: r["price"])
    return rates


def verify_bookable_rate(
    entity_key: str,
    check_in: str,
    check_out: str,
) -> dict | None:
    """Confirm Google returns an OTA rate plan with a booking deeplink."""
    try:
        detail = SearchHotels().get_details(
            entity_key,
            DateRange(
                check_in=date.fromisoformat(check_in),
                check_out=date.fromisoformat(check_out),
            ),
            location=Location(query=CITY_QUERY),
            currency=Currency.CAD,
        )
    except Exception:  # noqa: BLE001
        return None
    rates = extract_ota_rates(detail)
    if not rates:
        return None
    best = rates[0]
    return {
        "price_per_night": best["price"],
        "currency": CURRENCY,  # requested CAD; Google often mislabels USD
        "provider": best["provider"],
        "url": best["url"],
        "room": best.get("room"),
        "detail_display_price": getattr(detail, "display_price", None),
    }


def search_stay(check_in: str, check_out: str, nights: int) -> dict:
    filters = HotelSearchFilters(
        location=Location(query=CITY_QUERY),
        dates=DateRange(
            check_in=date.fromisoformat(check_in),
            check_out=date.fromisoformat(check_out),
        ),
        guests=GuestInfo(adults=ADULTS),
        currency=Currency.CAD,
        property_type=PropertyType.HOTELS,
        sort_by=SortBy.LOWEST_PRICE,
        hotel_class=list(range(MIN_STARS, 6)),
        brands=CHAIN_BRANDS,
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
        "km_from_center": None,
        "entity_key": None,
        "google_hotel_id": None,
        "booking_links": {},
        "bookable": False,
        "ota_provider": None,
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
        list_price = getattr(h, "display_price", None)
        if list_price is None:
            continue
        km = km_from_center(getattr(h, "latitude", None), getattr(h, "longitude", None))
        if km is None or km > MAX_KM_FROM_CENTER:
            continue
        # Google Hotels list price is a nightly rate for the date window —
        # it does NOT scale with nights (4-night ≈ 1-night for far-out dates).
        per_night = float(list_price)
        stay_total = per_night * nights if nights else per_night
        name = getattr(h, "name", None)
        entity_key = getattr(h, "entity_key", None)
        priced.append(
            {
                "name": name,
                "price": stay_total,
                "price_per_night": per_night,
                "list_price": per_night,
                "currency": getattr(h, "currency", None) or CURRENCY,
                "stars": getattr(h, "star_class", None),
                "rating": getattr(h, "overall_rating", None),
                "review_count": getattr(h, "review_count", None),
                "km_from_center": round(km, 2),
                "entity_key": entity_key,
                "google_hotel_id": getattr(h, "google_hotel_id", None),
            }
        )

    if not priced:
        empty["note"] = (
            f"No priced {MIN_STARS}★+ Marriott/Hyatt/Accor/Hilton/IHG/Four Seasons "
            f"hotels within {MAX_KM_FROM_CENTER} km of Plaça de Catalunya "
            "(dates may be too far out, or blocked)"
        )
        return empty

    # Placeholder filter uses the nightly list price (same fake chip on every hotel)
    if prices_look_like_placeholders(
        [{"price": p["list_price"]} for p in priced]
    ):
        mode_price, mode_n = Counter(
            round(float(p["list_price"]), 2) for p in priced
        ).most_common(1)[0]
        empty["note"] = (
            f"Ignored placeholder Google Hotels prices "
            f"({mode_n}/{len(priced)} hotels all show {CURRENCY} {mode_price:,.0f} — "
            "July 2027 inventory not bookable yet)"
        )
        return empty

    priced.sort(key=lambda x: x["price_per_night"])

    verified = None
    chosen = None
    if REQUIRE_OTA_RATES_FOR_ALERT:
        for cand in priced[:OTA_VERIFY_CANDIDATES]:
            key = cand.get("entity_key")
            if not key:
                continue
            time.sleep(0.8)
            verified = verify_bookable_rate(key, check_in, check_out)
            if verified:
                chosen = cand
                break
        if not verified or not chosen:
            empty["note"] = (
                "Google list prices found, but no bookable OTA rate/deeplink "
                f"for top {OTA_VERIFY_CANDIDATES} hotels — skipping alert"
            )
            empty["top"] = [
                {
                    "name": p["name"],
                    "price_per_night": p["price_per_night"],
                    "stars": p["stars"],
                    "km_from_center": p["km_from_center"],
                }
                for p in priced[:TOP_N]
            ]
            return empty
        per_night = float(verified["price_per_night"])
        stay_total = per_night * nights if nights else per_night
        links = booking_links(
            chosen["name"],
            check_in,
            check_out,
            entity_key=chosen.get("entity_key"),
            nights=nights,
            ota_url=verified["url"],
            ota_provider=verified["provider"],
        )
        return {
            "found": True,
            "bookable": True,
            "price": stay_total,
            "price_per_night": per_night,
            "nights": nights,
            "currency": CURRENCY,
            "name": chosen["name"],
            "stars": chosen["stars"],
            "rating": chosen["rating"],
            "km_from_center": chosen["km_from_center"],
            "entity_key": chosen.get("entity_key"),
            "google_hotel_id": chosen.get("google_hotel_id"),
            "booking_links": links,
            "ota_provider": verified["provider"],
            "top": priced[:TOP_N],
            "note": None,
        }

    best = priced[0]
    links = booking_links(
        best["name"],
        check_in,
        check_out,
        entity_key=best.get("entity_key"),
        nights=nights,
    )
    return {
        "found": True,
        "bookable": False,
        "price": best["price"],
        "price_per_night": best["price_per_night"],
        "nights": nights,
        "currency": best["currency"],
        "name": best["name"],
        "stars": best["stars"],
        "rating": best["rating"],
        "km_from_center": best["km_from_center"],
        "entity_key": best.get("entity_key"),
        "google_hotel_id": best.get("google_hotel_id"),
        "booking_links": links,
        "ota_provider": None,
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
        "- City: **Barcelona** (within "
        f"**{MAX_KM_FROM_CENTER} km** of Plaça de Catalunya — Gothic / Ramblas / central Eixample)",
        f"- Guests: {ADULTS} adult(s), {MIN_STARS}★+",
        f"- Alert: ≤ **{CURRENCY} {HOTEL_ALERT_BELOW_CAD:,.0f}** / night",
        "- Cruise Jul 15–24 = ship (**not** tracked)",
        "- Tracked: pre-cruise **Jul 11→15** + post-cruise **Jul 24→25** only",
        "",
        "| Stay | Total | /night | Hotel | km | Stars |",
        "|------|------:|-------:|-------|---:|------:|",
    ]
    for s in run["stays"]:
        if not s.get("found"):
            note = (s.get("note") or "no offers")[:40]
            lines.append(f"| {s['label']} | — | — | {note} | — | — |")
            continue
        name = (s.get("name") or "—")[:32]
        km = s.get("km_from_center")
        km_s = f"{km:.1f}" if km is not None else "—"
        lines.append(
            f"| {s['label']} | {CURRENCY} {s['price']:,.0f} | "
            f"{CURRENCY} {s.get('price_per_night', s['price']):,.0f} | "
            f"{name} | {km_s} | {s.get('stars') or '—'} |"
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


def format_booking_links_email(links: dict[str, str]) -> list[str]:
    lines: list[str] = []
    ota = links.get("ota")
    provider = links.get("ota_provider") or "OTA"
    if ota:
        lines.append(f"  BOOKABLE LINK ({provider}):")
        lines.append(f"    {ota}")
    else:
        lines.append("  BOOKABLE LINK: none verified — ignore this price")
    # Secondary search links (often show no inventory for far-out dates)
    secondary = []
    if links.get("google_hotels"):
        secondary.append(f"    Google Hotels (search): {links['google_hotels']}")
    if links.get("booking_com"):
        secondary.append(f"    Booking.com (search): {links['booking_com']}")
    if links.get("accor"):
        secondary.append(f"    Accor (direct): {links['accor']}")
    if secondary:
        lines.append("  Other search links (may show unavailable):")
        lines.extend(secondary)
    return lines


def format_booking_links_md(links: dict[str, str]) -> list[str]:
    lines: list[str] = []
    ota = links.get("ota")
    provider = links.get("ota_provider") or "OTA"
    if ota:
        lines.append(f"- **BOOKABLE LINK ({provider}):** {ota}")
    else:
        lines.append("- **BOOKABLE LINK:** none verified — ignore this price")
    extras = []
    if links.get("google_hotels"):
        extras.append(f"[Google Hotels search]({links['google_hotels']})")
    if links.get("booking_com"):
        extras.append(f"[Booking.com search]({links['booking_com']})")
    if links.get("accor"):
        extras.append(f"[Accor direct]({links['accor']})")
    if extras:
        lines.append(f"- Other search links (may show unavailable): {' · '.join(extras)}")
    return lines


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
        links = a.get("booking_links") or {}
        email_lines.extend(
            [
                f"{a['label']}:",
                f"  {CURRENCY} {a['price_per_night']:,.2f}/night "
                f"(total {CURRENCY} {a['price']:,.2f} for {a['nights']} night(s))",
                f"  Hotel: {a['name']}",
                f"  Stars: {a.get('stars') or 'n/a'}",
                f"  Distance: {a.get('km_from_center', 'n/a')} km from Plaça de Catalunya",
                f"  Check-in {a['check_in']} → out {a['check_out']}",
                *format_booking_links_email(links),
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
                f"- ~{a.get('km_from_center', 'n/a')} km from Plaça de Catalunya",
                *format_booking_links_md(links),
                "",
            ]
        )
    email_lines.extend(
        [
            "If a link says dates aren’t available yet, the scraped price wasn’t bookable — wait for inventory to open.",
            "",
        ]
    )
    md_lines.append(
        "_If a link says dates aren’t available yet, the scraped price wasn’t bookable — wait for inventory to open._"
    )
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
            and result.get("bookable")
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
                    "km_from_center": result.get("km_from_center"),
                    "entity_key": result.get("entity_key"),
                    "booking_links": result.get("booking_links") or {},
                    "ota_provider": result.get("ota_provider"),
                    "threshold": HOTEL_ALERT_BELOW_CAD,
                }
            )

    run = {
        "checked_at": checked_at,
        "city": CITY_QUERY,
        "center": {"name": "Plaça de Catalunya", "lat": CENTER_LAT, "lon": CENTER_LON},
        "max_km_from_center": MAX_KM_FROM_CENTER,
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
