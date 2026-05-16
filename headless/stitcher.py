"""Join contacts, transactions, and scraped PO/receiving data into CustomerRecords."""

from datetime import date, datetime
from typing import TypedDict

from parse_contacts import Contact, normalise
from parse_journal import Transaction

STAGE_LABELS = {
    1: "Enquiry",
    2: "Dress Selected",
    3: "Deposit Paid",
    4: "Ordered",
    5: "In Store",
    6: "Paid in Full",
}

DRESS_PREFIXES = {"L", "SO"}


class CustomerRecord(TypedDict):
    customer_name: str
    email: str
    mobile: str
    active_dress_txn: Transaction | None
    has_purchase_order: bool
    has_receiving: bool
    wedding_date: date | None
    days_to_wedding: int | None
    stage: int
    stage_label: str
    risk_level: str
    risk_reason: str
    flags: list


def _cell_contains(rows: list, value: str) -> bool:
    if not value:
        return False
    val = value.lower()
    return any(val in cell.lower() for row in rows for cell in row if cell)


def _compute_stage(
    active_dress_txn: Transaction | None,
    has_po: bool,
    has_receiving: bool,
) -> tuple[int, str]:
    if active_dress_txn is None:
        return 1, STAGE_LABELS[1]
    if active_dress_txn["bal_due"] == 0.0:
        return 6, STAGE_LABELS[6]
    if has_receiving:
        return 5, STAGE_LABELS[5]
    if has_po:
        return 4, STAGE_LABELS[4]
    if active_dress_txn["bal_due"] < active_dress_txn["trx_total"]:
        return 3, STAGE_LABELS[3]
    return 2, STAGE_LABELS[2]


def _compute_risk(
    stage: int,
    days_to_wedding: int | None,
    bal_due: float,
) -> tuple[str, str]:
    if days_to_wedding is None:
        return "ok", ""
    # Past weddings: flag outstanding balance as amber, otherwise ok
    if days_to_wedding < 0:
        if bal_due > 0:
            return "amber", "Wedding passed — balance still outstanding"
        return "ok", ""
    if days_to_wedding < 14 and stage < 6:
        return "critical", f"Wedding in {days_to_wedding} days — balance not cleared"
    if days_to_wedding < 30 and stage < 6:
        return "red", f"Wedding in {days_to_wedding} days — balance not cleared"
    if days_to_wedding < 60 and stage < 5:
        return "amber", f"Wedding in {days_to_wedding} days — dress not yet in store"
    if days_to_wedding < 90 and stage < 4:
        return "amber", f"Wedding in {days_to_wedding} days — no Purchase Order raised"
    return "ok", ""


def _collect_flags(record: "CustomerRecord") -> list[str]:
    flags: list[str] = []
    txn = record["active_dress_txn"]
    dtw = record["days_to_wedding"]

    if txn is None:
        flags.append("No dress transaction found")
        return flags

    if dtw is not None and dtw < 0 and txn["bal_due"] > 0:
        flags.append("Wedding passed — balance still owed")

    if txn["bal_due"] > 0:
        flags.append(f"Balance outstanding: £{txn['bal_due']:.2f}")

    if txn["is_dress_order"] and not record["has_purchase_order"]:
        flags.append("No Purchase Order raised")

    if record["has_purchase_order"] and not record["has_receiving"]:
        flags.append("Dress not yet received")

    return flags


def stitch(
    contacts: list,
    transactions: list,
    po_rows: list,
    receiving_rows: list,
) -> list:
    """
    Build one CustomerRecord per contact (pre-filtered to target year).
    Matches transactions to contacts by normalised full_name.
    Prefers L-prefix transactions over SO; most recent if multiple.
    Returns sorted by days_to_wedding ascending; no-date contacts at end.
    """
    today = datetime.now().date()

    # Index transactions by normalised customer name
    txns_by_customer: dict[str, list[Transaction]] = {}
    for txn in transactions:
        key = normalise(txn["customer"])
        txns_by_customer.setdefault(key, []).append(txn)

    dated: list[CustomerRecord] = []
    undated: list[CustomerRecord] = []

    for contact in contacts:
        key = normalise(contact["full_name"])
        customer_txns = txns_by_customer.get(key, [])

        # Find best active dress transaction: prefer L prefix, then SO, then most recent
        dress_txns = [t for t in customer_txns if t["prefix"] in DRESS_PREFIXES and t["is_dress_order"]]
        layaways = [t for t in dress_txns if t["prefix"] == "L"]
        specials = [t for t in dress_txns if t["prefix"] == "SO"]

        if layaways:
            active_dress_txn = max(layaways, key=lambda t: t["date"])
        elif specials:
            active_dress_txn = max(specials, key=lambda t: t["date"])
        else:
            active_dress_txn = None

        # PO and receiving match by customer name in scraped rows
        has_po = _cell_contains(po_rows, contact["full_name"])
        has_receiving = False
        if has_po:
            # Find PO numbers for this customer then check receiving
            customer_po_nums = [
                cell for row in po_rows for cell in row
                if cell and normalise(row[1] if len(row) > 1 else "") == key
                and cell.upper().startswith("PO")
            ]
            has_receiving = any(_cell_contains(receiving_rows, po) for po in customer_po_nums)

        wedding_date = contact["event_date"]
        days_to_wedding = (wedding_date - today).days if wedding_date else None

        has_po_flag = has_po
        has_receiving_flag = has_receiving
        stage, stage_label = _compute_stage(active_dress_txn, has_po_flag, has_receiving_flag)
        bal_due = active_dress_txn["bal_due"] if active_dress_txn else 0.0
        risk_level, risk_reason = _compute_risk(stage, days_to_wedding, bal_due)

        record: CustomerRecord = CustomerRecord(
            customer_name=contact["full_name"],
            email=contact["email"],
            mobile=contact["mobile"],
            active_dress_txn=active_dress_txn,
            has_purchase_order=has_po_flag,
            has_receiving=has_receiving_flag,
            wedding_date=wedding_date,
            days_to_wedding=days_to_wedding,
            stage=stage,
            stage_label=stage_label,
            risk_level=risk_level,
            risk_reason=risk_reason,
            flags=[],
        )
        record["flags"] = _collect_flags(record)

        if wedding_date:
            dated.append(record)
        else:
            undated.append(record)

    dated.sort(key=lambda r: r["wedding_date"])
    return dated + undated
