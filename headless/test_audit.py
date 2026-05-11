"""
Basic tests for BridalLive audit cross-reference logic and report formatting.
Run with: python -m pytest test_audit.py -v
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Patch out the gmail import before importing audit
import sys
sys.modules["gmail_client"] = MagicMock()

import audit


# ---------------------------------------------------------------------------
# Helpers to build synthetic report data
# ---------------------------------------------------------------------------

def make_sales(rows):
    return {"headers": ["ID", "Customer", "Date", "Salesperson", "Status", "Total", "Balance"], "rows": rows}

def make_pos(rows):
    return {"headers": ["PO", "Customer", "Supplier", "Status", "Date"], "rows": rows}

def make_payments(rows):
    return {"headers": ["ID", "Customer", "Linked TX", "Amount", "Date"], "rows": rows}

def make_receiving(rows):
    return {"headers": ["ID", "Customer", "PO Ref", "Date", "Qty"], "rows": rows}

def days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# 2A — Payments with no Sales Order
# ---------------------------------------------------------------------------

class TestPaymentsWithNoSalesOrder:

    def test_flags_payment_with_no_matching_sales_order(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        payments = make_payments([["P01", "Jane Smith", "9999", "£300", "01/03/2026"]])
        result = audit.cross_reference(sales, make_pos([]), payments, make_receiving([]))
        assert len(result["critical"]) == 1
        assert result["critical"][0]["type"] == "Payment without Sales Order"
        assert "Jane Smith" in result["critical"][0]["customer"]

    def test_no_flag_when_sales_order_exists(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        payments = make_payments([["P01", "Alice Brown", "1001", "£300", "01/03/2026"]])
        result = audit.cross_reference(sales, make_pos([]), payments, make_receiving([]))
        assert len(result["critical"]) == 0
        assert result["compliant"] >= 1

    def test_multiple_payments_mixed(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        payments = make_payments([
            ["P01", "Alice Brown", "1001", "£300", "01/03/2026"],  # linked — ok
            ["P02", "Ghost Customer", "8888", "£500", "01/03/2026"],  # no SO — critical
        ])
        result = audit.cross_reference(sales, make_pos([]), payments, make_receiving([]))
        assert len(result["critical"]) == 1


# ---------------------------------------------------------------------------
# 2B — Open Sales Orders with no Purchase Order
# ---------------------------------------------------------------------------

class TestOpenSalesOrdersWithNoPO:

    def test_flags_open_so_with_no_po(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        result = audit.cross_reference(sales, make_pos([]), make_payments([]), make_receiving([]))
        nv = [x for x in result["needs_verification"] if x["type"] == "Open Sales Order with no Purchase Order"]
        assert len(nv) == 1
        assert nv[0]["tx_id"] == "1001"

    def test_no_flag_when_po_linked(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        pos = make_pos([["PO500", "Alice Brown", "Maggie Sottero", "ordered", days_ago(5), "1001"]])
        result = audit.cross_reference(sales, pos, make_payments([]), make_receiving([]))
        nv = [x for x in result["needs_verification"] if x["type"] == "Open Sales Order with no Purchase Order"]
        assert len(nv) == 0

    def test_completed_sales_order_not_flagged(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "completed", "£1200", "£0"]])
        result = audit.cross_reference(sales, make_pos([]), make_payments([]), make_receiving([]))
        nv = [x for x in result["needs_verification"] if x["type"] == "Open Sales Order with no Purchase Order"]
        assert len(nv) == 0


# ---------------------------------------------------------------------------
# 2C — Purchase Orders not received
# ---------------------------------------------------------------------------

class TestPOsNotReceived:

    def test_flags_po_overdue_no_receiving(self):
        pos = make_pos([["PO500", "Alice Brown", "Supplier", "ordered", days_ago(20)]])
        result = audit.cross_reference(make_sales([]), pos, make_payments([]), make_receiving([]))
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        assert len(overdue) == 1
        assert overdue[0]["po_num"] == "PO500"

    def test_recent_po_goes_to_pending_not_critical(self):
        pos = make_pos([["PO501", "Bob Smith", "Supplier", "ordered", days_ago(5)]])
        result = audit.cross_reference(make_sales([]), pos, make_payments([]), make_receiving([]))
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        pending = [x for x in result["pending"] if "PO501" in x.get("po_num", "")]
        assert len(overdue) == 0
        assert len(pending) == 1

    def test_no_flag_when_receiving_record_exists(self):
        pos = make_pos([["PO500", "Alice Brown", "Supplier", "ordered", days_ago(20)]])
        receiving = make_receiving([["R01", "Alice Brown", "PO500", days_ago(3), "1"]])
        result = audit.cross_reference(make_sales([]), pos, make_payments([]), receiving)
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        assert len(overdue) == 0

    def test_boundary_exactly_14_days(self):
        # 14 days old — should still be pending, not critical (> 14 required)
        pos = make_pos([["PO502", "Carol Jones", "Supplier", "ordered", days_ago(14)]])
        result = audit.cross_reference(make_sales([]), pos, make_payments([]), make_receiving([]))
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        assert len(overdue) == 0


# ---------------------------------------------------------------------------
# 2D — Receiving records with no PO
# ---------------------------------------------------------------------------

class TestReceivingWithNoPO:

    def test_flags_receiving_with_no_po(self):
        receiving = make_receiving([["R01", "Alice Brown", "PO999", days_ago(2), "1"]])
        result = audit.cross_reference(make_sales([]), make_pos([]), make_payments([]), receiving)
        orphan = [x for x in result["critical"] if x["type"] == "Receiving record with no Purchase Order"]
        assert len(orphan) == 1

    def test_no_flag_when_po_exists(self):
        pos = make_pos([["PO999", "Alice Brown", "Supplier", "received", days_ago(10)]])
        receiving = make_receiving([["R01", "Alice Brown", "PO999", days_ago(2), "1"]])
        result = audit.cross_reference(make_sales([]), pos, make_payments([]), receiving)
        orphan = [x for x in result["critical"] if x["type"] == "Receiving record with no Purchase Order"]
        assert len(orphan) == 0


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

class TestFormatReport:

    def _findings(self, critical=None, nv=None, pending=None, compliant=0):
        return {
            "critical": critical or [],
            "needs_verification": nv or [],
            "pending": pending or [],
            "compliant": compliant,
        }

    def test_summary_counts_appear(self):
        findings = self._findings(
            critical=[{"type": "x", "customer": "A", "detail": "d", "action": "a"}],
            nv=[{"type": "x", "customer": "B", "tx_id": "1", "detail": "d", "action": "a"}],
            compliant=5,
        )
        report = audit.format_report(findings, 10)
        assert "Critical issues:      1" in report
        assert "Needs verification:   1" in report
        assert "Compliant:            5" in report

    def test_all_clear_message_when_no_issues(self):
        report = audit.format_report(self._findings(compliant=3), 10)
        assert "All reviewed transactions appear compliant" in report

    def test_critical_section_present(self):
        findings = self._findings(
            critical=[{"type": "Payment without Sales Order", "customer": "Jane Smith",
                        "detail": "£300 payment, no SO", "action": "Raise SO"}]
        )
        report = audit.format_report(findings, 5)
        assert "CRITICAL ISSUES" in report
        assert "Jane Smith" in report

    def test_pending_section_present(self):
        findings = self._findings(
            pending=[{"type": "PO pending — monitor", "customer": "Bob", "po_num": "PO123",
                      "detail": "placed 5 days ago"}]
        )
        report = audit.format_report(findings, 5)
        assert "PENDING / MONITOR" in report
        assert "PO123" in report

    def test_report_includes_period_and_date(self):
        report = audit.format_report(self._findings(), 90)
        assert "90" in report or datetime.now().strftime("%Y") in report
