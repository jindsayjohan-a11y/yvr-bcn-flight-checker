#!/usr/bin/env python3
"""Email a biweekly summary of daily lowest YVR→BCN prices."""

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


def parse_checked_day(checked_at: str) -> date | None:
    """Parse '2026-08-08 05:36 UTC' (or ISO) into a UTC date."""
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


def load_daily_lows(path: Path) -> dict[date, dict]:
    """Map calendar day → best check that day (lowest cheapest price)."""
    by_day: dict[date, dict] = {}
    if not path.exists():
        return by_day

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
            cheapest = run.get("cheapest") or {}
            if day is None or not cheapest.get("found") or cheapest.get("price") is None:
                # Still record the day as checked with no price
                if day is not None and day not in by_day:
                    by_day[day] = {
                        "price": None,
                        "outbound": None,
                        "airlines": None,
                        "checked_at": run.get("checked_at"),
                    }
                continue

            price = float(cheapest["price"])
            row = {
                "price": price,
                "outbound": cheapest.get("outbound"),
                "airlines": ", ".join(cheapest.get("airlines") or []) or None,
                "checked_at": run.get("checked_at"),
                "currency": cheapest.get("currency", CURRENCY),
            }
            prev = by_day.get(day)
            if prev is None or prev.get("price") is None or price < prev["price"]:
                by_day[day] = row
    return by_day


def build_summary(daily: dict[date, dict], end: date, days: int = DAYS) -> tuple[str, str]:
    start = end - timedelta(days=days - 1)
    lines = [
        f"YVR → BCN biweekly price summary",
        f"Period: {start.isoformat()} → {end.isoformat()} (UTC)",
        f"Route: outbound Jul 16–18 2027, return Jul 25 2027",
        "",
        f"{'Date':<12} {'Lowest':>12}  Outbound    Airlines",
        "-" * 60,
    ]
    priced_days = []
    for i in range(days):
        day = start + timedelta(days=i)
        row = daily.get(day)
        if not row or row.get("price") is None:
            lines.append(f"{day.isoformat():<12} {'—':>12}  —           no priced check")
            continue
        priced_days.append(row["price"])
        airlines = (row.get("airlines") or "—")[:24]
        outbound = row.get("outbound") or "—"
        lines.append(
            f"{day.isoformat():<12} {CURRENCY} {row['price']:>7,.0f}  "
            f"{outbound:<10}  {airlines}"
        )

    lines.append("-" * 60)
    if priced_days:
        best = min(priced_days)
        lines.append(f"Best in period: {CURRENCY} {best:,.0f}")
        lines.append(f"Days with a price: {len(priced_days)} / {days}")
    else:
        lines.append("No priced checks in this period yet (July 2027 may still be unpublished).")
    lines.append("")
    lines.append("This is automated research only — confirm on Google Flights before booking.")

    body = "\n".join(lines) + "\n"
    subject = f"YVR→BCN biweekly summary ({start.isoformat()} to {end.isoformat()})"
    return subject, body


def main() -> int:
    end = datetime.now(timezone.utc).date()
    daily = load_daily_lows(HISTORY_PATH)
    subject, body = build_summary(daily, end=end, days=DAYS)
    print(body)
    SUMMARY_PATH = ROOT / "data" / "biweekly_summary.txt"
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(body)

    ok = send_email(subject, body, to_addr=DEFAULT_EMAIL_TO)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
