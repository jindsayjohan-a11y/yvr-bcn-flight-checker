#!/usr/bin/env python3
"""Email a biweekly summary of daily lowest YVR→BCN prices by cabin."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mailer import DEFAULT_EMAIL_TO, send_email

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "data" / "history.jsonl"
DAYS = 14
CURRENCY = "CAD"
CABINS = (
    ("economy", "Economy"),
    ("premium-economy", "Premium economy"),
    ("business", "Business"),
)


def parse_checked_day(checked_at: str) -> date | None:
    text = (checked_at or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            if fmt == "%Y-%m-%d":
                return datetime.strptime(text[:10], fmt).date()
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).date()
    except ValueError:
        return None


def cabin_cheapest(run: dict, cabin: str) -> dict | None:
    cabins = run.get("cabins") or {}
    if cabin in cabins:
        return (cabins[cabin] or {}).get("cheapest")
    if cabin == "economy":
        return run.get("cheapest")
    return None


def load_daily_lows_by_cabin(path: Path) -> dict[str, dict[date, dict]]:
    """cabin → day → lowest priced row that day."""
    by_cabin: dict[str, dict[date, dict]] = {c: {} for c, _ in CABINS}
    if not path.exists():
        return by_cabin

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                run = json.loads(line)
            except json.JSONDecodeError:
                continue
            day = parse_checked_day(run.get("checked_at", ""))
            if day is None:
                continue

            for cabin, _label in CABINS:
                cheapest = cabin_cheapest(run, cabin) or {}
                bucket = by_cabin[cabin]
                if not cheapest.get("found") or cheapest.get("price") is None:
                    if day not in bucket:
                        bucket[day] = {"price": None}
                    continue
                price = float(cheapest["price"])
                row = {
                    "price": price,
                    "outbound": cheapest.get("outbound"),
                    "airlines": ", ".join(cheapest.get("airlines") or []) or None,
                }
                prev = bucket.get(day)
                if prev is None or prev.get("price") is None or price < prev["price"]:
                    bucket[day] = row
    return by_cabin


def section_for_cabin(
    label: str, daily: dict[date, dict], start: date, days: int
) -> tuple[list[str], list[float]]:
    lines = [f"{label}", "-" * 60]
    priced: list[float] = []
    for i in range(days):
        day = start + timedelta(days=i)
        row = daily.get(day)
        if not row or row.get("price") is None:
            lines.append(f"{day.isoformat():<12} {'—':>12}  —           no priced check")
            continue
        priced.append(row["price"])
        airlines = (row.get("airlines") or "—")[:24]
        outbound = row.get("outbound") or "—"
        lines.append(
            f"{day.isoformat():<12} {CURRENCY} {row['price']:>7,.0f}  "
            f"{outbound:<10}  {airlines}"
        )
    lines.append("-" * 60)
    if priced:
        lines.append(f"Best in period: {CURRENCY} {min(priced):,.0f}")
        lines.append(f"Days with a price: {len(priced)} / {days}")
    else:
        lines.append("No priced checks in this period yet.")
    lines.append("")
    return lines, priced


def build_summary(
    by_cabin: dict[str, dict[date, dict]], end: date, days: int = DAYS
) -> tuple[str, str]:
    start = end - timedelta(days=days - 1)
    lines = [
        "YVR → BCN biweekly price summary",
        f"Period: {start.isoformat()} → {end.isoformat()} (UTC)",
        "Route: outbound Jul 16–18 2027, return Jul 25 2027",
        "",
        "Alert thresholds: Economy ≤ 1,100 · Premium economy ≤ 1,600 · Business ≤ 2,500",
        "",
    ]
    for cabin, label in CABINS:
        section, _ = section_for_cabin(label, by_cabin.get(cabin, {}), start, days)
        lines.extend(section)

    lines.append("This is automated research only — confirm on Google Flights before booking.")
    body = "\n".join(lines) + "\n"
    subject = f"YVR→BCN biweekly summary ({start.isoformat()} to {end.isoformat()})"
    return subject, body


def main() -> int:
    end = datetime.now(timezone.utc).date()
    by_cabin = load_daily_lows_by_cabin(HISTORY_PATH)
    subject, body = build_summary(by_cabin, end=end, days=DAYS)
    print(body)
    summary_path = ROOT / "data" / "biweekly_summary.txt"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(body)

    ok = send_email(subject, body, to_addr=DEFAULT_EMAIL_TO)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
