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
from gmail_client import send_email as gmail_send

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
    today_str = datetime.now().strftime("%d/%m/%Y")
    gmail_send(
        to=RECIPIENT,
        subject=f"BridalLive Audit Report — {today_str}",
        body=report,
    )
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
