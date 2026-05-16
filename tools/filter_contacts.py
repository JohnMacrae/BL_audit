#!/usr/bin/env python3
"""Filter a BridalLive contacts CSV to brides with event dates in a given year or later.

Usage: python tools/filter_contacts.py input.csv output.csv [min_year]
Default min_year: 2026
"""

import csv
import sys
from datetime import datetime


def filter_contacts(in_path: str, out_path: str, min_year: int = 2026) -> int:
    kept = 0
    with open(in_path, encoding="utf-8-sig", errors="replace") as f_in, \
         open(out_path, "w", newline="", encoding="utf-8") as f_out:
        reader = csv.DictReader(f_in)
        writer = csv.DictWriter(f_out, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            d = row.get("Event Date", "").strip()
            if not d:
                continue
            try:
                if datetime.strptime(d, "%d/%m/%Y").year >= min_year:
                    writer.writerow(row)
                    kept += 1
            except ValueError:
                continue
    return kept


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("Usage: python filter_contacts.py input.csv output.csv [min_year]")
    min_year = int(sys.argv[3]) if len(sys.argv) > 3 else 2026
    kept = filter_contacts(sys.argv[1], sys.argv[2], min_year)
    print(f"Wrote {kept} contacts with event date >= {min_year} → {sys.argv[2]}")
