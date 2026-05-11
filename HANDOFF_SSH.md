# BL_Audit — SSH Session Handoff

You are Claude Code continuing work on the BridalLive headless audit tool.
Read this document fully before doing anything. All tasks are defined here.

---

## Context

Serenity Brides (Julie's bridal boutique) uses BridalLive as its POS.
Staff have not been following correct transaction workflow since a manager left.
This project audits their compliance by navigating BridalLive headlessly,
extracting data from four report pages, cross-referencing for gaps,
and emailing a structured report.

This project is completely separate from the property management stack
(property-agent, sbbrain, etc.) — do not reference those tools.

---

## Repo

```
https://github.com/JohnMacrae/BL_audit
```

The git remote URL with token is in `/volume1/docker/BL_Audit/.git/config`.
If the directory doesn't exist yet:

```bash
cat /volume1/docker/BL_Audit/git-config.txt   # get the token from here
git clone https://TOKEN@github.com/JohnMacrae/BL_audit.git /volume1/docker/BL_Audit
```

---

## Current file structure

```
BL_Audit/
├── HANDOVER.md          — project background (read-only reference)
├── SKILL.md             — Claude-in-Chrome skill (read-only reference)
├── audit-prompt.md      — per-transaction audit prompt (read-only reference)
├── .gitignore           — excludes git-config.txt and headless/.env
└── headless/
    ├── audit.py         — Playwright headless runner (needs refactoring — see Task 1)
    ├── Dockerfile        — mcr.microsoft.com/playwright/python base image
    ├── compose.yml      — mounts gmail_client.py + jramacrae token from NAS
    ├── .env             — credentials, NOT in git (see below if missing)
    └── test_audit.py    — pytest suite (currently broken — see Task 1)
```

---

## The .env file

Not in git. Should exist at `/volume1/docker/BL_Audit/headless/.env`.
If missing, create it with exactly this content:

```
BL_USER=claude
BL_PASSWORD=Thebot2026!!??
REPORT_EMAIL=jramacrae@gmail.com
AUDIT_DAYS=90
GMAIL_TOKEN_PATH=/gmail-config/token.json
GMAIL_CREDS_PATH=/gmail-config/credentials.json
GMAIL_SCOPE_TIER=send
```

---

## TASK 1 — Refactor audit.py to fix the test suite

### Problem

`test_audit.py` imports `audit.py`, which has a top-level Playwright import:
```python
from playwright.async_api import async_playwright
```
This causes the entire test suite to fail unless Playwright is installed,
which it isn't outside Docker. pytest must run without Docker.

### Solution

Split `audit.py` into two files:

- **`audit_logic.py`** — pure Python only. Contains all the logic functions.
  No Playwright imports. No Gmail imports. No `os.getenv` at module level.
- **`audit.py`** — thin runner only. Imports from `audit_logic`. Handles
  Playwright, login, page navigation, Gmail send.

Then update `test_audit.py` to import from `audit_logic` instead of `audit`.

---

### Exact content for audit_logic.py

Create `/volume1/docker/BL_Audit/headless/audit_logic.py` with this content:

```python
"""
Pure logic for BridalLive audit — no Playwright, no Gmail, no I/O.
Imported by audit.py (runner) and test_audit.py (tests).
"""

from datetime import datetime, timedelta


def cell_contains(rows, value):
    return any(value and value.lower() in cell.lower() for row in rows for cell in row if cell)


def find_date(row):
    for cell in row:
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(cell.strip(), fmt)
            except ValueError:
                pass
    return None


def cross_reference(sales, pos, payments, receiving):
    critical, needs_verification, pending = [], [], []
    compliant = 0

    sales_rows = sales.get("rows", [])
    po_rows = pos.get("rows", [])
    payment_rows = payments.get("rows", [])
    receiving_rows = receiving.get("rows", [])
    today = datetime.now()

    # 2A — Payments with no Sales Order
    for pmt in payment_rows:
        if not pmt:
            continue
        linked_id = next((c for c in pmt if c.isdigit() and len(c) > 2), None)
        customer = pmt[1] if len(pmt) > 1 else "Unknown"
        amount = next((c for c in pmt if "£" in c or "$" in c), "unknown amount")
        if linked_id and not cell_contains(sales_rows, linked_id):
            critical.append({
                "type": "Payment without Sales Order",
                "customer": customer,
                "detail": f"Payment of {amount} recorded — no matching Sales Order found (ref: {linked_id})",
                "action": "Raise a Sales Order retrospectively and link this payment to it",
            })
        else:
            compliant += 1

    # 2B — Open Sales Orders with no linked PO
    for sale in sales_rows:
        if not sale:
            continue
        status = next((c for c in sale if c.lower() in ("open", "active", "in progress")), None)
        if not status:
            continue
        tx_id = sale[0]
        customer = sale[1] if len(sale) > 1 else "Unknown"
        if not cell_contains(po_rows, tx_id):
            needs_verification.append({
                "type": "Open Sales Order with no Purchase Order",
                "customer": customer,
                "tx_id": tx_id,
                "detail": "Open Sales Order has no linked Purchase Order",
                "action": "Confirm with staff whether item is in stock or requires a special order to be raised",
            })
        else:
            compliant += 1

    # 2C — POs not received
    for po in po_rows:
        if not po:
            continue
        status = next((c for c in po if c.lower() in ("ordered", "submitted", "sent")), None)
        if not status:
            continue
        po_num = po[0]
        customer = po[1] if len(po) > 1 else "Unknown"
        po_date = find_date(po)
        age_days = (today - po_date).days if po_date else 999

        if not cell_contains(receiving_rows, po_num):
            if age_days > 14:
                critical.append({
                    "type": "Purchase Order overdue for receiving",
                    "customer": customer,
                    "po_num": po_num,
                    "detail": f"PO {po_num} status '{status}', no receiving record found (~{age_days} days old)",
                    "action": "Chase supplier for delivery status; receive into BridalLive when item arrives",
                })
            else:
                pending.append({
                    "type": "PO pending — monitor",
                    "customer": customer,
                    "po_num": po_num,
                    "detail": f"PO {po_num} placed recently (~{age_days} days ago), not yet received",
                })
        else:
            compliant += 1

    # 2D — Receiving records with no PO
    for recv in receiving_rows:
        if not recv:
            continue
        po_ref = next((c for c in recv if c.upper().startswith("PO") or (c.isdigit() and len(c) > 2)), None)
        customer = recv[1] if len(recv) > 1 else "Unknown"
        if po_ref and not cell_contains(po_rows, po_ref):
            critical.append({
                "type": "Receiving record with no Purchase Order",
                "customer": customer,
                "po_ref": po_ref,
                "detail": f"Item received (ref: {po_ref}) but no matching Purchase Order on record",
                "action": "Raise a Purchase Order retrospectively to account for this stock",
            })

    return {
        "critical": critical,
        "needs_verification": needs_verification,
        "pending": pending,
        "compliant": compliant,
    }


def format_report(findings, sales_count, period_days=90):
    today = datetime.now().strftime("%d/%m/%Y")
    period_start = (datetime.now() - timedelta(days=period_days)).strftime("%d/%m/%Y")
    sep = "=" * 56
    div = "-" * 56

    lines = [
        sep,
        "BRIDALLIVE TRANSACTION AUDIT REPORT",
        f"Period:               {period_start} – {today}",
        f"Generated:            {today}",
        f"Transactions reviewed: {sales_count}",
        sep,
        "",
        "SUMMARY",
        div,
        f"Critical issues:      {len(findings['critical'])}",
        f"Needs verification:   {len(findings['needs_verification'])}",
        f"Pending / monitor:    {len(findings['pending'])}",
        f"Compliant:            {findings['compliant']}",
        "",
    ]

    if findings["critical"]:
        lines += [sep, "CRITICAL ISSUES — ACTION REQUIRED", sep]
        for i, issue in enumerate(findings["critical"], 1):
            lines += [
                "",
                f"[ISSUE #{i}]",
                f"Type:       {issue['type']}",
                f"Customer:   {issue.get('customer', 'Unknown')}",
                f"Issue:      {issue['detail']}",
                f"Action:     {issue['action']}",
                div,
            ]

    if findings["needs_verification"]:
        lines += ["", sep, "NEEDS VERIFICATION — POSSIBLE GAPS", sep]
        for i, item in enumerate(findings["needs_verification"], 1):
            lines += [
                "",
                f"[ITEM #{i}]",
                f"Customer:       {item.get('customer', 'Unknown')}",
                f"Transaction ID: {item.get('tx_id', 'Unknown')}",
                f"Issue:          {item['detail']}",
                f"Action needed:  {item['action']}",
                div,
            ]

    if findings["pending"]:
        lines += ["", sep, "PENDING / MONITOR", sep]
        for i, item in enumerate(findings["pending"], 1):
            lines += [
                "",
                f"[ITEM #{i}]",
                f"PO Number:  {item.get('po_num', 'Unknown')}",
                f"Customer:   {item.get('customer', 'Unknown')}",
                f"Note:       {item['detail']}",
                div,
            ]

    if not findings["critical"] and not findings["needs_verification"]:
        lines += ["", sep, "All reviewed transactions appear compliant.", sep]

    return "\n".join(lines)
```

---

### Exact content for the refactored audit.py

Replace `/volume1/docker/BL_Audit/headless/audit.py` entirely with this:

```python
#!/usr/bin/env python3
"""
BridalLive Headless Audit — runner
Handles browser automation, login, data extraction, and email dispatch.
All logic lives in audit_logic.py.
"""

import asyncio
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

sys.path.insert(0, "/gmail")
from gmail_client import GmailClient

from audit_logic import cross_reference, format_report

BRIDALLIVE_URL = "https://app.bridallive.com"
PERIOD_DAYS = int(os.getenv("AUDIT_DAYS", "90"))
RECIPIENT = os.getenv("REPORT_EMAIL", "jramacrae@gmail.com")
BL_USER = os.getenv("BL_USER")
BL_PASSWORD = os.getenv("BL_PASSWORD")

EXTRACT_JS = """
() => {
    const headers = Array.from(document.querySelectorAll('table thead th'))
        .map(th => th.innerText.trim());
    let rows = Array.from(document.querySelectorAll('table tbody tr'))
        .map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim()));
    if (rows.length === 0) {
        rows = Array.from(document.querySelectorAll('[class*="row"],[class*="grid-row"]'))
            .map(r => Array.from(r.querySelectorAll('[class*="cell"],td'))
                .map(c => c.innerText.trim()).filter(Boolean))
            .filter(r => r.length > 2);
    }
    return { headers, rows };
}
"""

NAV_SCAN_JS = """
() => Array.from(document.querySelectorAll('a'))
    .filter(a => /report|purchase|receiving|layaway|transaction/i.test(a.innerText + a.href))
    .map(a => ({ text: a.innerText.trim(), href: a.href }))
"""


async def wait_for_table(page, timeout=20000):
    try:
        await page.wait_for_selector("table tbody tr", timeout=timeout)
    except Exception:
        pass


async def login(page):
    await page.goto(f"{BRIDALLIVE_URL}/app/login", wait_until="networkidle")
    if "/login" not in page.url:
        print("  Already logged in.")
        return

    await page.fill(
        'input[type="email"], input[name="email"], input[placeholder*="email" i]',
        BL_USER,
    )
    await page.fill('input[type="password"]', BL_PASSWORD)
    await page.click(
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Login"), button:has-text("Sign In")'
    )
    await page.wait_for_load_state("networkidle")

    if "/login" in page.url:
        raise RuntimeError("Login failed — check BL_USER / BL_PASSWORD in .env")
    print("  Login successful.")


async def get_report(page, primary_url, fallback_url=None):
    await page.goto(primary_url, wait_until="networkidle")

    if any(x in page.url for x in ["/login", "/dashboard"]) or \
            page.url.rstrip("/") == BRIDALLIVE_URL + "/app":
        if fallback_url:
            print(f"  Primary URL redirected, trying fallback: {fallback_url}")
            await page.goto(fallback_url, wait_until="networkidle")
        else:
            nav_links = await page.evaluate(NAV_SCAN_JS)
            return {"headers": [], "rows": [], "error": f"Redirected from {primary_url}",
                    "nav_links": nav_links}

    try:
        sel = page.locator('select').filter(has_text="Status")
        if await sel.count():
            await sel.first.select_option(label="All")
    except Exception:
        pass

    try:
        btn = page.locator('button:has-text("Run"), button:has-text("Search"), button:has-text("Filter")')
        if await btn.count():
            await btn.first.click()
            await page.wait_for_load_state("networkidle")
    except Exception:
        pass

    await wait_for_table(page)
    data = await page.evaluate(EXTRACT_JS)
    print(f"  Extracted {len(data['rows'])} rows from {page.url}")
    return data


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Step 0 — Login")
        await login(page)

        print("Step 1A — Sales Transactions")
        sales = await get_report(page, f"{BRIDALLIVE_URL}/app/reports/sales-transactions")

        print("Step 1B — Purchase Orders")
        pos = await get_report(
            page,
            f"{BRIDALLIVE_URL}/app/reports/purchase-orders",
            f"{BRIDALLIVE_URL}/app/purchaseorders",
        )

        print("Step 1C — Layaway / Payments")
        payments = await get_report(
            page,
            f"{BRIDALLIVE_URL}/app/reports/layaway",
            f"{BRIDALLIVE_URL}/app/reports/payments",
        )

        print("Step 1D — Receiving")
        receiving = await get_report(
            page,
            f"{BRIDALLIVE_URL}/app/reports/receiving",
            f"{BRIDALLIVE_URL}/app/inventory/receiving",
        )

        await browser.close()

    print("Step 2 — Cross-referencing...")
    findings = cross_reference(sales, pos, payments, receiving)

    report = format_report(findings, len(sales.get("rows", [])), PERIOD_DAYS)
    print("\n" + report)

    print(f"\nStep 3 — Emailing report to {RECIPIENT}...")
    gc = GmailClient()
    today_str = datetime.now().strftime("%d/%m/%Y")
    gc.send_email(
        to=RECIPIENT,
        subject=f"BridalLive Audit Report — {today_str}",
        body=report,
    )
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
```

---

### Exact content for the updated test_audit.py

Replace `/volume1/docker/BL_Audit/headless/test_audit.py` entirely with this:

```python
"""
Tests for BridalLive audit logic.
Run with: python -m pytest test_audit.py -v
No Playwright or Gmail required.
"""

import pytest
from datetime import datetime, timedelta

from audit_logic import cross_reference, format_report


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


class TestPaymentsWithNoSalesOrder:

    def test_flags_payment_with_no_matching_sales_order(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        payments = make_payments([["P01", "Jane Smith", "9999", "£300", "01/03/2026"]])
        result = cross_reference(sales, make_pos([]), payments, make_receiving([]))
        assert len(result["critical"]) == 1
        assert result["critical"][0]["type"] == "Payment without Sales Order"
        assert "Jane Smith" in result["critical"][0]["customer"]

    def test_no_flag_when_sales_order_exists(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        payments = make_payments([["P01", "Alice Brown", "1001", "£300", "01/03/2026"]])
        result = cross_reference(sales, make_pos([]), payments, make_receiving([]))
        assert len(result["critical"]) == 0
        assert result["compliant"] >= 1

    def test_multiple_payments_mixed(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        payments = make_payments([
            ["P01", "Alice Brown", "1001", "£300", "01/03/2026"],
            ["P02", "Ghost Customer", "8888", "£500", "01/03/2026"],
        ])
        result = cross_reference(sales, make_pos([]), payments, make_receiving([]))
        assert len(result["critical"]) == 1


class TestOpenSalesOrdersWithNoPO:

    def test_flags_open_so_with_no_po(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        result = cross_reference(sales, make_pos([]), make_payments([]), make_receiving([]))
        nv = [x for x in result["needs_verification"] if x["type"] == "Open Sales Order with no Purchase Order"]
        assert len(nv) == 1
        assert nv[0]["tx_id"] == "1001"

    def test_no_flag_when_po_linked(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "open", "£1200", "£900"]])
        pos = make_pos([["PO500", "Alice Brown", "Maggie Sottero", "ordered", days_ago(5), "1001"]])
        result = cross_reference(sales, pos, make_payments([]), make_receiving([]))
        nv = [x for x in result["needs_verification"] if x["type"] == "Open Sales Order with no Purchase Order"]
        assert len(nv) == 0

    def test_completed_sales_order_not_flagged(self):
        sales = make_sales([["1001", "Alice Brown", "01/01/2026", "Sarah", "completed", "£1200", "£0"]])
        result = cross_reference(sales, make_pos([]), make_payments([]), make_receiving([]))
        nv = [x for x in result["needs_verification"] if x["type"] == "Open Sales Order with no Purchase Order"]
        assert len(nv) == 0


class TestPOsNotReceived:

    def test_flags_po_overdue_no_receiving(self):
        pos = make_pos([["PO500", "Alice Brown", "Supplier", "ordered", days_ago(20)]])
        result = cross_reference(make_sales([]), pos, make_payments([]), make_receiving([]))
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        assert len(overdue) == 1
        assert overdue[0]["po_num"] == "PO500"

    def test_recent_po_goes_to_pending_not_critical(self):
        pos = make_pos([["PO501", "Bob Smith", "Supplier", "ordered", days_ago(5)]])
        result = cross_reference(make_sales([]), pos, make_payments([]), make_receiving([]))
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        pending = [x for x in result["pending"] if "PO501" in x.get("po_num", "")]
        assert len(overdue) == 0
        assert len(pending) == 1

    def test_no_flag_when_receiving_record_exists(self):
        pos = make_pos([["PO500", "Alice Brown", "Supplier", "ordered", days_ago(20)]])
        receiving = make_receiving([["R01", "Alice Brown", "PO500", days_ago(3), "1"]])
        result = cross_reference(make_sales([]), pos, make_payments([]), receiving)
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        assert len(overdue) == 0

    def test_boundary_exactly_14_days(self):
        pos = make_pos([["PO502", "Carol Jones", "Supplier", "ordered", days_ago(14)]])
        result = cross_reference(make_sales([]), pos, make_payments([]), make_receiving([]))
        overdue = [x for x in result["critical"] if x["type"] == "Purchase Order overdue for receiving"]
        assert len(overdue) == 0


class TestReceivingWithNoPO:

    def test_flags_receiving_with_no_po(self):
        receiving = make_receiving([["R01", "Alice Brown", "PO999", days_ago(2), "1"]])
        result = cross_reference(make_sales([]), make_pos([]), make_payments([]), receiving)
        orphan = [x for x in result["critical"] if x["type"] == "Receiving record with no Purchase Order"]
        assert len(orphan) == 1

    def test_no_flag_when_po_exists(self):
        pos = make_pos([["PO999", "Alice Brown", "Supplier", "received", days_ago(10)]])
        receiving = make_receiving([["R01", "Alice Brown", "PO999", days_ago(2), "1"]])
        result = cross_reference(make_sales([]), pos, make_payments([]), receiving)
        orphan = [x for x in result["critical"] if x["type"] == "Receiving record with no Purchase Order"]
        assert len(orphan) == 0


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
        report = format_report(findings, 10)
        assert "Critical issues:      1" in report
        assert "Needs verification:   1" in report
        assert "Compliant:            5" in report

    def test_all_clear_message_when_no_issues(self):
        report = format_report(self._findings(compliant=3), 10)
        assert "All reviewed transactions appear compliant" in report

    def test_critical_section_present(self):
        findings = self._findings(
            critical=[{"type": "Payment without Sales Order", "customer": "Jane Smith",
                       "detail": "£300 payment, no SO", "action": "Raise SO"}]
        )
        report = format_report(findings, 5)
        assert "CRITICAL ISSUES" in report
        assert "Jane Smith" in report

    def test_pending_section_present(self):
        findings = self._findings(
            pending=[{"type": "PO pending — monitor", "customer": "Bob", "po_num": "PO123",
                      "detail": "placed 5 days ago"}]
        )
        report = format_report(findings, 5)
        assert "PENDING / MONITOR" in report
        assert "PO123" in report

    def test_report_includes_period_and_date(self):
        report = format_report(self._findings(), 90)
        assert datetime.now().strftime("%Y") in report
```

---

## TASK 2 — Run the tests

Once the three files above are written:

```bash
cd /volume1/docker/BL_Audit/headless
pip install pytest   # if not already installed
python -m pytest test_audit.py -v
```

All 16 tests should pass. If any fail, fix the logic in `audit_logic.py` —
do not modify the tests unless a test itself is wrong.

---

## TASK 3 — Verify the GmailClient signature

Before running the full audit, check that `audit.py` is calling `GmailClient`
correctly:

```bash
grep -n "def send_email\|def __init__\|class GmailClient" \
  /volume1/docker/gmail-mcp/gmail_client.py
```

The audit runner calls:
```python
gc = GmailClient()
gc.send_email(to=RECIPIENT, subject=..., body=...)
```

If the constructor requires arguments, or `send_email` uses different parameter
names, update the relevant lines in `audit.py` to match.

---

## TASK 4 — Commit and push everything

```bash
cd /volume1/docker/BL_Audit
git add headless/audit_logic.py headless/audit.py headless/test_audit.py
git commit -m "Refactor: split audit logic into audit_logic.py so tests run without Playwright"
git push
```

---

## TASK 5 — First Docker run

```bash
cd /volume1/docker/BL_Audit/headless
docker compose run --rm bl-audit
```

First run is slow (builds image, downloads Chromium). Watch the output for:

- `Login successful` — good
- `Primary URL redirected` — note the fallback URL that works; hardcode it
- `Extracted 0 rows` — selector mismatch; investigate the BridalLive DOM
- Any Python exception — fix before re-running

If the login page structure differs from expected (email field not found),
add `page.screenshot(path="/tmp/login.png")` before the fill calls in
`audit.py`, then `docker cp` the screenshot out to inspect it.

---

## Known gaps to address after first successful run

1. Hardcode the correct report URLs once confirmed (remove fallback logic)
2. Confirm table selectors match BridalLive's actual DOM
3. Confirm GmailClient sends successfully to jramacrae@gmail.com
