#!/usr/bin/env python3
"""
BridalLive Headless Audit
Navigates BridalLive, extracts data from 4 report pages via JS injection,
cross-references for compliance gaps, and emails the report.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

sys.path.insert(0, "/gmail")
from gmail_client import GmailClient

BRIDALLIVE_URL = "https://app.bridallive.com"
PERIOD_DAYS = int(os.getenv("AUDIT_DAYS", "90"))
RECIPIENT = os.getenv("REPORT_EMAIL", "jramacrae@gmail.com")
BL_USER = os.getenv("BL_USER")
BL_PASSWORD = os.getenv("BL_PASSWORD")


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

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
    """Navigate to a report page and return extracted table data."""
    await page.goto(primary_url, wait_until="networkidle")

    # Detect redirect to dashboard / login
    if any(x in page.url for x in ["/login", "/dashboard"]) or page.url.rstrip("/") == BRIDALLIVE_URL + "/app":
        if fallback_url:
            print(f"  Primary URL redirected, trying fallback: {fallback_url}")
            await page.goto(fallback_url, wait_until="networkidle")
        else:
            nav_links = await page.evaluate(NAV_SCAN_JS)
            return {"headers": [], "rows": [], "error": f"Redirected from {primary_url}", "nav_links": nav_links}

    # Try to set Status = All
    try:
        sel = page.locator('select').filter(has_text="Status")
        if await sel.count():
            await sel.first.select_option(label="All")
    except Exception:
        pass

    # Click Run / Search if present
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


# ---------------------------------------------------------------------------
# Cross-reference logic
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(findings, sales_count):
    today = datetime.now().strftime("%d/%m/%Y")
    period_start = (datetime.now() - timedelta(days=PERIOD_DAYS)).strftime("%d/%m/%Y")
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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

    report = format_report(findings, len(sales.get("rows", [])))
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
