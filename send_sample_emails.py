#!/usr/bin/env python3
"""Send sample alert + biweekly summary emails (for testing)."""

from __future__ import annotations

from mailer import DEFAULT_EMAIL_TO, send_email


def main() -> int:
    alert_ok = send_email(
        subject="[SAMPLE] Price alert: YVR→BCN Economy CAD 1,049 · Premium economy CAD 1,520 · Business CAD 2,380",
        body=(
            "YVR → BCN price alert\n\n"
            "THIS IS A SAMPLE — not a real fare check.\n\n"
            "Checked: 2026-08-08 06:00 UTC\n"
            "Return: 2027-07-25\n\n"
            "Economy: CAD 1,049.00 (threshold CAD 1,100)\n"
            "  Outbound: 2027-07-17\n"
            "  Airlines: Air Canada, Lufthansa\n\n"
            "Premium economy: CAD 1,520.00 (threshold CAD 1,600)\n"
            "  Outbound: 2027-07-16\n"
            "  Airlines: Air Canada\n\n"
            "Business: CAD 2,380.00 (threshold CAD 2,500)\n"
            "  Outbound: 2027-07-18\n"
            "  Airlines: Lufthansa\n\n"
            "Confirm on Google Flights before booking:\n"
            "https://www.google.com/travel/flights\n"
        ),
        to_addr=DEFAULT_EMAIL_TO,
    )

    summary_ok = send_email(
        subject="[SAMPLE] YVR→BCN biweekly summary (2026-07-26 to 2026-08-08)",
        body=(
            "YVR → BCN biweekly price summary\n"
            "Period: 2026-07-26 → 2026-08-08 (UTC)\n"
            "Route: outbound Jul 16–18 2027, return Jul 25 2027\n"
            "\n"
            "THIS IS A SAMPLE — example numbers only.\n"
            "\n"
            "Date               Lowest  Outbound    Airlines\n"
            "------------------------------------------------------------\n"
            "2026-07-26     CAD   1,289  2027-07-16  Air Canada\n"
            "2026-07-27     CAD   1,265  2027-07-17  Lufthansa\n"
            "2026-07-28     CAD   1,241  2027-07-16  Air Canada\n"
            "2026-07-29     CAD   1,198  2027-07-18  United, Air Canada\n"
            "2026-07-30     CAD   1,176  2027-07-17  Lufthansa\n"
            "2026-07-31     CAD   1,155  2027-07-16  Air Canada\n"
            "2026-08-01     CAD   1,132  2027-07-17  WestJet, KLM\n"
            "2026-08-02     CAD   1,118  2027-07-18  Air Canada\n"
            "2026-08-03     CAD   1,105  2027-07-16  Lufthansa\n"
            "2026-08-04     CAD   1,092  2027-07-17  Air Canada\n"
            "2026-08-05     CAD   1,078  2027-07-18  United\n"
            "2026-08-06     CAD   1,061  2027-07-16  Air Canada, Lufthansa\n"
            "2026-08-07     CAD   1,055  2027-07-17  Lufthansa\n"
            "2026-08-08     CAD   1,049  2027-07-17  Air Canada, Lufthansa\n"
            "------------------------------------------------------------\n"
            "Best in period: CAD 1,049\n"
            "Days with a price: 14 / 14\n"
            "\n"
            "This is automated research only — confirm on Google Flights before booking.\n"
        ),
        to_addr=DEFAULT_EMAIL_TO,
    )

    if alert_ok and summary_ok:
        print("Both sample emails sent.")
        return 0
    print("One or both sample emails failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
