"""Parse the BridalLive Transaction Item Journal CSV export into structured records."""

import csv
import os
import re
from datetime import date, datetime
from typing import TypedDict

JOURNAL_PATH = os.getenv("JOURNAL_PATH", "/data/transactionItemJournal.csv")
INHOUSE_VENDORS = {"SB", "SV", "RD"}
MIN_DRESS_PRICE = 50.0


class JournalItem(TypedDict):
    vendor: str
    item_name: str
    color: str
    size: str
    price: float
    qty: int
    bal_due: float
    trx_total: float


class Transaction(TypedDict):
    trx_id: str
    prefix: str
    date: date
    customer: str
    items: list
    bal_due: float
    trx_total: float
    is_dress_order: bool


def _parse_currency(value: str) -> float:
    """Convert '£1,200.00' or '-£75.00' to float. Returns 0.0 on failure."""
    cleaned = re.sub(r"[£$,\s�]", "", value).strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_date(value: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _prefix(trx_id: str) -> str:
    m = re.match(r"^([A-Za-z]+)", trx_id.strip())
    return m.group(1).upper() if m else ""


def load_journal(path: str = JOURNAL_PATH) -> list:
    """
    Parse the Transaction Item Journal CSV.

    Skips the 6-row BridalLive header block and the final "Total" row.
    Excludes R-prefix (return/refund) transactions.
    Returns list of Transaction dicts sorted by date ascending.
    """
    rows_by_trx: dict[str, list[list[str]]] = {}
    order: list[str] = []

    with open(path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        all_rows = list(reader)

    # Find the header row (contains "Trx #")
    data_start = 0
    for i, row in enumerate(all_rows):
        if row and "Trx #" in row[0]:
            data_start = i + 1
            break

    for row in all_rows[data_start:]:
        if not row or not row[0].strip():
            continue
        trx_id = row[0].strip()
        # Skip total footer row
        if trx_id.lower().startswith("total"):
            continue
        prefix = _prefix(trx_id)
        # Skip returns
        if prefix == "R":
            continue
        if trx_id not in rows_by_trx:
            rows_by_trx[trx_id] = []
            order.append(trx_id)
        rows_by_trx[trx_id].append(row)

    transactions: list[Transaction] = []
    for trx_id in order:
        item_rows = rows_by_trx[trx_id]
        first = item_rows[0]

        trx_date = _parse_date(first[1]) if len(first) > 1 else None
        customer = first[2].strip() if len(first) > 2 else ""
        bal_due = _parse_currency(first[10]) if len(first) > 10 else 0.0
        trx_total = _parse_currency(first[11]) if len(first) > 11 else 0.0

        items: list[JournalItem] = []
        for r in item_rows:
            vendor = r[3].strip() if len(r) > 3 else ""
            item_name = r[4].strip() if len(r) > 4 else ""
            color = r[5].strip() if len(r) > 5 else ""
            size = r[6].strip() if len(r) > 6 else ""
            price = _parse_currency(r[7]) if len(r) > 7 else 0.0
            qty_str = r[8].strip() if len(r) > 8 else "1"
            try:
                qty = int(qty_str)
            except ValueError:
                qty = 1
            items.append(JournalItem(
                vendor=vendor, item_name=item_name, color=color, size=size,
                price=price, qty=qty, bal_due=bal_due, trx_total=trx_total,
            ))

        is_dress_order = any(
            item["vendor"] not in INHOUSE_VENDORS and item["price"] > MIN_DRESS_PRICE
            for item in items
        )

        transactions.append(Transaction(
            trx_id=trx_id,
            prefix=_prefix(trx_id),
            date=trx_date or date.min,
            customer=customer,
            items=items,
            bal_due=bal_due,
            trx_total=trx_total,
            is_dress_order=is_dress_order,
        ))

    transactions.sort(key=lambda t: t["date"])
    return transactions
