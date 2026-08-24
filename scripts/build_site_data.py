#!/usr/bin/env python3
"""Build docs/data.json from flight + hotel (+ optional Skyscanner) history."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "docs" / "data.json"

MAX_POINTS = 400
CABINS = ("economy", "premium-economy", "business")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def cabin_cheapest(block: dict | None) -> dict | None:
    if not block:
        return None
    cheapest = block.get("cheapest")
    if isinstance(cheapest, dict) and cheapest.get("price") is not None:
        return {
            "price": float(cheapest["price"]),
            "outbound": cheapest.get("outbound"),
            "airlines": cheapest.get("airlines"),
        }
    found = [
        r
        for r in (block.get("results") or [])
        if r.get("found") and r.get("price") is not None
    ]
    if not found:
        return None
    best = min(found, key=lambda r: float(r["price"]))
    return {
        "price": float(best["price"]),
        "outbound": best.get("outbound"),
        "airlines": best.get("airlines"),
    }


def trim(points: list) -> list:
    return points[-MAX_POINTS:] if len(points) > MAX_POINTS else points


def build_flights(rows: list[dict]) -> dict:
    series = {c: [] for c in CABINS}
    for row in rows:
        ts = row.get("checked_at")
        if not ts:
            continue
        for cabin in CABINS:
            ch = cabin_cheapest((row.get("cabins") or {}).get(cabin))
            if ch:
                series[cabin].append([ts, ch["price"], ch.get("outbound")])

    latest = rows[-1] if rows else {}
    thresholds = latest.get("alert_thresholds") or {
        "economy": 1100,
        "premium-economy": 1600,
        "business": 2500,
    }
    latest_cabins = {
        cabin: cabin_cheapest((latest.get("cabins") or {}).get(cabin))
        for cabin in CABINS
    }
    return {
        "checked_at": latest.get("checked_at"),
        "thresholds": thresholds,
        "latest": latest_cabins,
        "series": {k: trim(v) for k, v in series.items()},
        "scan_count": len(rows),
        "route": {
            "origin": latest.get("origin", "YVR"),
            "destination": latest.get("destination", "BCN"),
            "outbound_dates": latest.get("outbound_dates")
            or ["2027-07-09", "2027-07-10", "2027-07-11", "2027-07-12"],
            "return_date": latest.get("return_date") or "2027-07-25",
        },
    }


def build_hotels(rows: list[dict]) -> dict:
    series = {"pre-cruise": [], "post-cruise": []}
    for row in rows:
        ts = row.get("checked_at")
        if not ts:
            continue
        for stay in row.get("stays") or []:
            sid = stay.get("id")
            if sid not in series:
                continue
            if stay.get("found") and stay.get("price_per_night") is not None:
                series[sid].append(
                    [
                        ts,
                        float(stay["price_per_night"]),
                        stay.get("name"),
                        bool(stay.get("bookable")),
                    ]
                )

    latest = rows[-1] if rows else {}
    latest_stays = []
    for stay in latest.get("stays") or []:
        latest_stays.append(
            {
                "id": stay.get("id"),
                "label": stay.get("label"),
                "check_in": stay.get("check_in"),
                "check_out": stay.get("check_out"),
                "nights": stay.get("nights"),
                "found": bool(stay.get("found")),
                "bookable": bool(stay.get("bookable")),
                "price_per_night": stay.get("price_per_night"),
                "price": stay.get("price"),
                "name": stay.get("name"),
                "stars": stay.get("stars"),
                "km_from_center": stay.get("km_from_center"),
                "booking_links": stay.get("booking_links") or {},
                "note": stay.get("note"),
            }
        )

    return {
        "checked_at": latest.get("checked_at"),
        "threshold": latest.get("alert_below_cad", 200),
        "latest": latest_stays,
        "series": {k: trim(v) for k, v in series.items()},
        "scan_count": len(rows),
    }


def build_skyscanner(rows: list[dict]) -> dict:
    series = {c: [] for c in CABINS}
    for row in rows:
        ts = row.get("checked_at")
        if not ts:
            continue
        for cabin in CABINS:
            ch = cabin_cheapest((row.get("cabins") or {}).get(cabin))
            if ch:
                series[cabin].append([ts, ch["price"], ch.get("outbound")])

    latest = rows[-1] if rows else {}
    return {
        "enabled": bool(rows),
        "checked_at": latest.get("checked_at"),
        "thresholds": latest.get("alert_thresholds")
        or {"economy": 1100, "premium-economy": 1600, "business": 2500},
        "latest": {
            cabin: cabin_cheapest((latest.get("cabins") or {}).get(cabin))
            for cabin in CABINS
        },
        "series": {k: trim(v) for k, v in series.items()},
        "scan_count": len(rows),
        "note": None
        if rows
        else "Add repo secret RAPIDAPI_KEY to enable daily Skyscanner scans.",
    }


def main() -> int:
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "trip": {
            "flights": "Outbound Jul 9–12 · Return Jul 25, 2027",
            "hotels": "Pre-cruise Jul 11→15 · Post-cruise Jul 24→25",
        },
        "flights": build_flights(read_jsonl(DATA / "history.jsonl")),
        "hotels": build_hotels(read_jsonl(DATA / "hotel_history.jsonl")),
        "skyscanner": build_skyscanner(read_jsonl(DATA / "skyscanner_history.jsonl")),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
