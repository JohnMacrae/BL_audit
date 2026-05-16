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
    # Navigate to root — hash router will redirect to #/login if not authenticated
    await page.goto(BRIDALLIVE_URL, wait_until="domcontentloaded")

    if "login" not in page.url:
        print("  Already logged in.")
        return

    print(f"  Login page URL: {page.url}")
    print("  Waiting for login form...")
    try:
        await page.wait_for_selector("input", timeout=20000)
    except Exception:
        pass

    inputs = await page.evaluate("""
        () => Array.from(document.querySelectorAll('input')).map(i => ({
            type: i.type, name: i.name, id: i.id, placeholder: i.placeholder
        }))
    """)
    print(f"  Inputs found: {inputs}")

    if not inputs:
        body = await page.evaluate("() => document.body.innerText")
        print(f"  Body text: {body[:600]}")
        raise RuntimeError("Login form did not render — no inputs found")

    await page.locator("input[type='email'], input[type='text']").first.fill(BL_USER)
    await page.locator("input[type='password']").first.fill(BL_PASSWORD)
    await page.locator(
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Login"), button:has-text("Sign In")'
    ).first.click()
    await page.wait_for_load_state("networkidle")

    if "login" in page.url:
        raise RuntimeError("Login failed — check BL_USER / BL_PASSWORD in .env")
    print(f"  Login successful. URL: {page.url}")

    # Print nav links so we can identify correct report hash routes
    nav_links = await page.evaluate(NAV_SCAN_JS)
    print(f"  Nav links found: {nav_links}")


async def get_report(page, primary_url, fallback_url=None):
    await page.goto(primary_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    if "login" in page.url or "dashboard" in page.url:
        if fallback_url:
            print(f"  Primary URL redirected ({page.url}), trying fallback: {fallback_url}")
            await page.goto(fallback_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
        else:
            nav_links = await page.evaluate(NAV_SCAN_JS)
            print(f"  Redirected from {primary_url} — nav links: {nav_links}")
            return {"headers": [], "rows": [], "error": f"Redirected from {primary_url}"}

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
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        print("Step 0 — Login")
        await login(page)

        print("Step 1A — Sales Transactions")
        sales = await get_report(
            page,
            f"{BRIDALLIVE_URL}/#/sales-orders",
            f"{BRIDALLIVE_URL}/#/transactions",
        )

        print("Step 1B — Purchase Orders")
        pos = await get_report(page, f"{BRIDALLIVE_URL}/#/purchase-orders")

        print("Step 1C — Layaway / Payments")
        payments = await get_report(
            page,
            f"{BRIDALLIVE_URL}/#/layaway",
            f"{BRIDALLIVE_URL}/#/payments",
        )

        print("Step 1D — Receiving")
        receiving = await get_report(
            page,
            f"{BRIDALLIVE_URL}/#/receiving",
            f"{BRIDALLIVE_URL}/#/inventory",
        )

        await context.close()
        await browser.close()

    print("Step 2 — Cross-referencing...")
    findings = cross_reference(sales, pos, payments, receiving)

    report = format_report(findings, len(sales.get("rows", [])), PERIOD_DAYS)
    print("\n" + report)

    print(f"\nStep 3 — Emailing audit report to {RECIPIENT}...")
    today_str = datetime.now().strftime("%d/%m/%Y")
    gmail_send(
        to=RECIPIENT,
        subject=f"BridalLive Audit Report — {today_str}",
        body=report,
    )
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
