"""Tests for parse_journal, parse_contacts, and stitcher modules."""

import csv
import io
import textwrap
from datetime import date, datetime

import pytest

from parse_contacts import Contact, contacts_by_name, load_contacts, normalise
from parse_journal import Transaction, _parse_currency, _prefix, load_journal
from stitcher import (
    _collect_flags,
    _compute_risk,
    _compute_stage,
    stitch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _journal_csv(rows: list[list[str]]) -> str:
    """Build a minimal journal CSV string with BridalLive's 6-row header."""
    lines = [
        "Transaction Item Journal Report,,,,,,,,,,,",
        "Serenity Brides,,,,,,,,,,,",
        "Report Date/Time: 01/01/2026,,,,,,,,,,",
        "Dates: 01/01/2025 - 01/01/2026,,,,,,,,,,,",
        ",,,,,,,,,,",
        ",,,,,,,,,,",
        "Trx #,Date,Contact,Vendor,Item Name,Color,Size,Adj Price,Qty,VAT,Bal Due,Trx Total",
    ]
    for row in rows:
        lines.append(",".join(row))
    lines.append("Total,,,,,,,£1000.00,1,£166.67,,")
    return "\n".join(lines)


def _contacts_csv(rows: list[dict]) -> str:
    fields = ["First Name", "Last Name", "Address 1", "Address 2", "City", "State",
              "Zip Code", "Country", "Home Phone", "Work Phone", "Mobile Phone",
              "Email", "Pref. Contact Method", "How Heard", "Associate", "Category",
              "Event Type", "Event Date", "Time of Day", "Location", "Number of Members",
              "Budget", "Budget Range", "Formality", "Status"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in fields})
    return out.getvalue()


def _write_tmp(tmp_path, filename: str, content: str):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# TestNormalise
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_strips_and_lowercases(self):
        assert normalise("  Alice Brown  ") == "alice brown"

    def test_collapses_double_spaces(self):
        assert normalise("Emily  Oram") == "emily oram"

    def test_preserves_suffix(self):
        assert normalise("Nicky Wiffen RYC") == "nicky wiffen ryc"


# ---------------------------------------------------------------------------
# TestParseJournal
# ---------------------------------------------------------------------------

class TestParseJournal:
    def test_loads_basic_transaction(self, tmp_path):
        csv_str = _journal_csv([
            ["L 100", "01/06/2026", "Alice Brown", "JA", "Aria (88095)", "Ivory", "14",
             "£999.00", "1", "£166.50", "£499.00", "£999.00"],
        ])
        path = _write_tmp(tmp_path, "journal.csv", csv_str)
        txns = load_journal(path)
        assert len(txns) == 1
        t = txns[0]
        assert t["trx_id"] == "L 100"
        assert t["prefix"] == "L"
        assert t["customer"] == "Alice Brown"
        assert t["bal_due"] == 499.0
        assert t["trx_total"] == 999.0

    def test_skips_r_prefix(self, tmp_path):
        csv_str = _journal_csv([
            ["R 10", "01/06/2026", "Alice Brown", "SB", "Overpayment", "", "",
             "-£25.00", "1", "£0.00", "£0.00", "-£25.00"],
            ["L 100", "02/06/2026", "Alice Brown", "JA", "Aria (88095)", "Ivory", "14",
             "£999.00", "1", "£166.50", "£0.00", "£999.00"],
        ])
        path = _write_tmp(tmp_path, "journal.csv", csv_str)
        txns = load_journal(path)
        assert len(txns) == 1
        assert txns[0]["trx_id"] == "L 100"

    def test_groups_multi_row_transaction(self, tmp_path):
        csv_str = _journal_csv([
            ["L 100", "01/06/2026", "Alice Brown", "JA", "Aria", "Ivory", "14",
             "£999.00", "1", "£166.50", "£499.00", "£1099.00"],
            ["L 100", "01/06/2026", "Alice Brown", "SB", "Alteration Package", "N/A", "",
             "£100.00", "1", "£16.67", "£499.00", "£1099.00"],
        ])
        path = _write_tmp(tmp_path, "journal.csv", csv_str)
        txns = load_journal(path)
        assert len(txns) == 1
        assert len(txns[0]["items"]) == 2

    def test_is_dress_order_true_for_external_vendor(self, tmp_path):
        csv_str = _journal_csv([
            ["SO 200", "01/06/2026", "Bob Smith", "JA", "Aria (88095)", "Ivory", "14",
             "£999.00", "1", "£166.50", "£999.00", "£999.00"],
        ])
        path = _write_tmp(tmp_path, "journal.csv", csv_str)
        txns = load_journal(path)
        assert txns[0]["is_dress_order"] is True

    def test_is_dress_order_false_for_inhouse_only(self, tmp_path):
        csv_str = _journal_csv([
            ["S 999", "01/06/2026", "Carol Jones", "SB", "Appointment Fee", "", "",
             "£10.00", "1", "£1.67", "£0.00", "£10.00"],
        ])
        path = _write_tmp(tmp_path, "journal.csv", csv_str)
        txns = load_journal(path)
        assert txns[0]["is_dress_order"] is False

    def test_sorted_by_date_ascending(self, tmp_path):
        csv_str = _journal_csv([
            ["L 102", "15/06/2026", "Bob Smith", "JA", "Dress", "", "",
             "£999.00", "1", "£0.00", "£0.00", "£999.00"],
            ["L 101", "01/06/2026", "Alice Brown", "JA", "Dress", "", "",
             "£999.00", "1", "£0.00", "£0.00", "£999.00"],
        ])
        path = _write_tmp(tmp_path, "journal.csv", csv_str)
        txns = load_journal(path)
        assert txns[0]["trx_id"] == "L 101"
        assert txns[1]["trx_id"] == "L 102"


class TestParseCurrency:
    def test_pound_sign(self):
        assert _parse_currency("£999.00") == 999.0

    def test_zero(self):
        assert _parse_currency("£0.00") == 0.0

    def test_with_comma(self):
        assert _parse_currency("£1,200.00") == 1200.0

    def test_negative(self):
        assert _parse_currency("-£25.00") == -25.0

    def test_unparseable(self):
        assert _parse_currency("N/A") == 0.0


class TestPrefix:
    def test_l(self):    assert _prefix("L 100") == "L"
    def test_so(self):   assert _prefix("SO 200") == "SO"
    def test_s(self):    assert _prefix("S 1000") == "S"
    def test_r(self):    assert _prefix("R 10") == "R"


# ---------------------------------------------------------------------------
# TestParseContacts
# ---------------------------------------------------------------------------

class TestParseContacts:
    def _make_row(self, first, last, event_date="", status="A"):
        return {"First Name": first, "Last Name": last, "Event Date": event_date,
                "Status": status, "Mobile Phone": "07700900000", "Email": "test@test.com"}

    def test_filters_by_min_year(self, tmp_path):
        csv_str = _contacts_csv([
            self._make_row("Alice", "Brown", "14/06/2026"),
            self._make_row("Past", "Bride", "01/01/2025"),
        ])
        path = _write_tmp(tmp_path, "contacts.csv", csv_str)
        contacts = load_contacts(path, min_year=2026)
        assert len(contacts) == 1
        assert contacts[0]["full_name"] == "Alice Brown"

    def test_full_name_construction(self, tmp_path):
        csv_str = _contacts_csv([self._make_row("Nicky", "Wiffen RYC", "14/08/2026")])
        path = _write_tmp(tmp_path, "contacts.csv", csv_str)
        contacts = load_contacts(path)
        assert contacts[0]["full_name"] == "Nicky Wiffen RYC"

    def test_blank_event_date_included_at_end(self, tmp_path):
        csv_str = _contacts_csv([
            self._make_row("Alice", "Brown", "14/06/2026"),
            self._make_row("No", "Date", ""),
        ])
        path = _write_tmp(tmp_path, "contacts.csv", csv_str)
        contacts = load_contacts(path)
        assert len(contacts) == 2
        assert contacts[-1]["full_name"] == "No Date"
        assert contacts[-1]["event_date"] is None

    def test_sorted_by_event_date(self, tmp_path):
        csv_str = _contacts_csv([
            self._make_row("Bob", "Smith", "30/08/2026"),
            self._make_row("Alice", "Brown", "14/06/2026"),
        ])
        path = _write_tmp(tmp_path, "contacts.csv", csv_str)
        contacts = load_contacts(path)
        assert contacts[0]["full_name"] == "Alice Brown"
        assert contacts[1]["full_name"] == "Bob Smith"

    def test_contacts_by_name_lookup(self, tmp_path):
        csv_str = _contacts_csv([self._make_row("Nicky", "Wiffen RYC", "14/08/2026")])
        path = _write_tmp(tmp_path, "contacts.csv", csv_str)
        contacts = load_contacts(path)
        lookup = contacts_by_name(contacts)
        assert "nicky wiffen ryc" in lookup


# ---------------------------------------------------------------------------
# TestComputeStage
# ---------------------------------------------------------------------------

def _make_txn(prefix="L", bal_due=500.0, trx_total=1000.0, is_dress=True) -> Transaction:
    return Transaction(
        trx_id=f"{prefix} 100", prefix=prefix, date=date(2026, 1, 1),
        customer="Alice Brown", items=[], bal_due=bal_due,
        trx_total=trx_total, is_dress_order=is_dress,
    )


class TestComputeStage:
    def test_stage_1_no_transaction(self):
        stage, label = _compute_stage(None, False, False)
        assert stage == 1
        assert label == "Enquiry"

    def test_stage_2_dress_selected_full_balance(self):
        txn = _make_txn(bal_due=1000.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, False, False)
        assert stage == 2
        assert label == "Dress Selected"

    def test_stage_3_deposit_paid(self):
        txn = _make_txn(prefix="SO", bal_due=500.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, False, False)
        assert stage == 3
        assert label == "Deposit Paid"

    def test_stage_4_has_po(self):
        txn = _make_txn(prefix="SO", bal_due=500.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, True, False)
        assert stage == 4
        assert label == "Ordered"

    def test_layaway_deposit_paid_jumps_to_stage_5(self):
        txn = _make_txn(prefix="L", bal_due=500.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, False, False)
        assert stage == 5
        assert label == "In Store"

    def test_layaway_no_deposit_stays_stage_2(self):
        txn = _make_txn(prefix="L", bal_due=1000.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, False, False)
        assert stage == 2

    def test_stage_5_has_receiving(self):
        txn = _make_txn(bal_due=500.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, True, True)
        assert stage == 5
        assert label == "In Store"

    def test_stage_6_paid_in_full(self):
        txn = _make_txn(bal_due=0.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, True, True)
        assert stage == 6
        assert label == "Paid in Full"

    def test_stage_6_paid_without_po(self):
        txn = _make_txn(bal_due=0.0, trx_total=1000.0)
        stage, label = _compute_stage(txn, False, False)
        assert stage == 6


# ---------------------------------------------------------------------------
# TestComputeRisk
# ---------------------------------------------------------------------------

class TestComputeRisk:
    def test_critical_under_14_not_paid(self):
        level, reason = _compute_risk(3, 10, 500.0)
        assert level == "critical"

    def test_red_under_30_not_paid(self):
        level, reason = _compute_risk(3, 25, 500.0)
        assert level == "red"

    def test_amber_under_60_not_in_store(self):
        level, reason = _compute_risk(3, 45, 500.0)
        assert level == "amber"

    def test_amber_under_90_not_ordered(self):
        level, reason = _compute_risk(2, 75, 1000.0)
        assert level == "amber"

    def test_ok_paid_in_full_any_timeline(self):
        level, _ = _compute_risk(6, 10, 0.0)
        assert level == "ok"

    def test_ok_no_wedding_date(self):
        level, reason = _compute_risk(3, None, 500.0)
        assert level == "ok"
        assert reason == ""

    def test_past_wedding_with_balance_amber(self):
        level, _ = _compute_risk(3, -5, 300.0)
        assert level == "amber"

    def test_past_wedding_no_balance_ok(self):
        level, _ = _compute_risk(6, -5, 0.0)
        assert level == "ok"

    def test_boundary_exactly_14_days_not_critical(self):
        # < 14 is critical; exactly 14 is red
        level, _ = _compute_risk(3, 14, 500.0)
        assert level == "red"

    def test_boundary_exactly_30_days_not_red(self):
        # < 30 is red; exactly 30 is amber
        level, _ = _compute_risk(3, 30, 500.0)
        assert level == "amber"


# ---------------------------------------------------------------------------
# TestCollectFlags
# ---------------------------------------------------------------------------

def _make_record(active_dress_txn=None, has_po=False, has_receiving=False,
                 days_to_wedding=100, bal_due=0.0, is_dress_order=True, prefix="SO"):
    txn = None
    if active_dress_txn is not None:
        txn = _make_txn(prefix=prefix, bal_due=bal_due, trx_total=1000.0, is_dress=is_dress_order)
    return {
        "customer_name": "Alice Brown",
        "email": "", "mobile": "",
        "active_dress_txn": txn,
        "has_purchase_order": has_po,
        "has_receiving": has_receiving,
        "wedding_date": date(2026, 6, 14),
        "days_to_wedding": days_to_wedding,
        "expected_delivery": None,
        "stage": 3, "stage_label": "Deposit Paid",
        "sale_status": "sold",
        "risk_level": "ok", "risk_reason": "", "flags": [],
    }


class TestCollectFlags:
    def test_no_transaction_flag(self):
        record = _make_record(active_dress_txn=None)
        flags = _collect_flags(record)
        assert any("No dress transaction" in f for f in flags)

    def test_past_wedding_with_balance(self):
        record = _make_record(active_dress_txn=True, days_to_wedding=-5, bal_due=300.0)
        flags = _collect_flags(record)
        assert any("Wedding passed" in f for f in flags)

    def test_balance_outstanding_flag(self):
        record = _make_record(active_dress_txn=True, bal_due=300.0)
        flags = _collect_flags(record)
        assert any("£300.00" in f for f in flags)

    def test_no_po_flag_for_so_dress_order(self):
        record = _make_record(active_dress_txn=True, has_po=False, is_dress_order=True,
                              bal_due=500.0, prefix="SO")
        flags = _collect_flags(record)
        assert any("Purchase Order" in f for f in flags)

    def test_no_po_flag_suppressed_for_layaway(self):
        record = _make_record(active_dress_txn=True, has_po=False, is_dress_order=True,
                              bal_due=500.0, prefix="L")
        flags = _collect_flags(record)
        assert not any("Purchase Order" in f for f in flags)

    def test_not_received_flag(self):
        record = _make_record(active_dress_txn=True, has_po=True, has_receiving=False,
                              bal_due=500.0, prefix="SO")
        flags = _collect_flags(record)
        assert any("not yet received" in f for f in flags)

    def test_not_received_flag_suppressed_for_layaway(self):
        record = _make_record(active_dress_txn=True, has_po=True, has_receiving=False,
                              bal_due=500.0, prefix="L")
        flags = _collect_flags(record)
        assert not any("not yet received" in f for f in flags)

    def test_clean_record_no_flags(self):
        record = _make_record(active_dress_txn=True, has_po=True, has_receiving=True, bal_due=0.0)
        flags = _collect_flags(record)
        assert flags == []


# ---------------------------------------------------------------------------
# TestStitch
# ---------------------------------------------------------------------------

def _make_contact(full_name: str, event_date: date | None = date(2026, 6, 14)) -> Contact:
    return Contact(
        full_name=full_name, first_name=full_name.split()[0],
        last_name=" ".join(full_name.split()[1:]),
        email="", mobile="", event_date=event_date, status="A",
    )


def _make_txn_dict(trx_id: str, customer: str, prefix: str = "L",
                   bal_due: float = 500.0, trx_total: float = 1000.0,
                   is_dress: bool = True, txn_date: date = date(2026, 1, 1)):
    return Transaction(
        trx_id=trx_id, prefix=prefix, date=txn_date,
        customer=customer, items=[], bal_due=bal_due,
        trx_total=trx_total, is_dress_order=is_dress,
    )


class TestStitch:
    def test_single_customer_matched(self):
        contacts = [_make_contact("Alice Brown")]
        txns = [_make_txn_dict("L 100", "Alice Brown")]
        records = stitch(contacts, txns, [], [])
        assert len(records) == 1
        assert records[0]["active_dress_txn"] is not None
        assert records[0]["active_dress_txn"]["trx_id"] == "L 100"

    def test_name_case_insensitive(self):
        contacts = [_make_contact("Alice Brown")]
        txns = [_make_txn_dict("L 100", "ALICE BROWN")]
        records = stitch(contacts, txns, [], [])
        assert records[0]["active_dress_txn"] is not None

    def test_double_space_in_journal(self):
        contacts = [_make_contact("Emily Oram")]
        txns = [_make_txn_dict("SO 935", "Emily  Oram")]
        records = stitch(contacts, txns, [], [])
        assert records[0]["active_dress_txn"] is not None

    def test_no_transaction_gives_stage_1(self):
        contacts = [_make_contact("Ghost Bride")]
        records = stitch(contacts, [], [], [])
        assert records[0]["stage"] == 1

    def test_sorted_by_wedding_date(self):
        contacts = [
            _make_contact("Bob Smith", date(2026, 8, 30)),
            _make_contact("Alice Brown", date(2026, 6, 14)),
        ]
        records = stitch(contacts, [], [], [])
        assert records[0]["customer_name"] == "Alice Brown"
        assert records[1]["customer_name"] == "Bob Smith"

    def test_no_date_contact_at_end(self):
        contacts = [
            _make_contact("No Date Bride", None),
            _make_contact("Alice Brown", date(2026, 6, 14)),
        ]
        records = stitch(contacts, [], [], [])
        assert records[-1]["customer_name"] == "No Date Bride"

    def test_prefers_l_over_so(self):
        contacts = [_make_contact("Alice Brown")]
        txns = [
            _make_txn_dict("SO 200", "Alice Brown", prefix="SO", txn_date=date(2026, 2, 1)),
            _make_txn_dict("L 100", "Alice Brown", prefix="L", txn_date=date(2026, 1, 1)),
        ]
        records = stitch(contacts, txns, [], [])
        assert records[0]["active_dress_txn"]["trx_id"] == "L 100"

    def test_stage_6_when_paid_in_full(self):
        contacts = [_make_contact("Alice Brown")]
        txns = [_make_txn_dict("L 100", "Alice Brown", bal_due=0.0)]
        records = stitch(contacts, txns, [], [])
        assert records[0]["stage"] == 6
