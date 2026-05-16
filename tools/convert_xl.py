#!/usr/bin/env python3
"""Convert a BridalLive Excel export to clean UTF-8 CSV.

Usage: python tools/convert_xl.py input.xlsx output.csv
"""

import csv
import sys


def convert(xlsx_path: str, csv_path: str) -> None:
    try:
        import openpyxl
    except ImportError:
        sys.exit("openpyxl not installed — run: pip install openpyxl")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    row_count = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(["" if v is None else str(v) for v in row])
            row_count += 1
    print(f"Converted {xlsx_path} → {csv_path} ({row_count} rows)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: python convert_xl.py input.xlsx output.csv")
    convert(sys.argv[1], sys.argv[2])
