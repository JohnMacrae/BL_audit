---
name: bridallive-audit
description: Use this skill whenever the user wants to audit BridalLive transactions for process compliance. Triggers include: "audit BridalLive", "check sales orders", "find missing purchase orders", "check transactions in BridalLive", "are special orders being recorded correctly", "audit the girls' transactions", "check staff are following process in BridalLive", or any request to review, inspect, or validate BridalLive sales, orders, or receiving records. Always use this skill when BridalLive and auditing/checking/reviewing are mentioned together.
---

# BridalLive Transaction Audit Skill

This skill navigates the BridalLive web interface at `app.bridallive.com`, extracts data from four key report pages using JavaScript injection, cross-references the data to identify compliance gaps, and produces a structured audit report.

The primary goal is to find transactions where **correct process has not been followed** — specifically:
- Sales that exist without a proper Sales Order
- Sales Orders with no linked Special/Purchase Order where one is required
- Purchase Orders where items have not been received and recorded
- Payments/Layaway records with no corresponding Sales Order

---

## STEP 0 — ENSURE BRIDALLIVE IS OPEN AND LOGGED IN

Check whether BridalLive is already open in the browser.

Use `list_connected_browsers` and `read_page` to check if `app.bridallive.com` is the current page or an open tab.

**If BridalLive is not open:**
```
navigate to: https://app.bridallive.com
```

After navigation, check the page. If a login screen is presented, tell the user:
> "BridalLive is showing a login screen. Please log in via your browser and then ask me to continue the audit."

Do NOT attempt to enter credentials. Wait for explicit instruction to continue.

**If already logged in**, proceed directly to Step 1.

---

## STEP 1 — COLLECT DATA FROM ALL FOUR REPORT PAGES

Work through each report in sequence. For each report, navigate to the URL, wait for the table to render, then extract all visible data using JavaScript injection. Do **not** screenshot unless the JS extraction fails.

### Efficiency rules
- Always prefer `javascript_tool` over `get_page_text` for structured table data — it returns cleaner, parseable rows
- Always prefer `javascript_tool` over `read_page` for bulk extraction
- Only use `computer` (click/screenshot) when a filter dropdown or date picker must be set that cannot be driven by JS
- Extract all rows in a single JS call per page — never loop row by row with separate tool calls
- If a report has pagination, collect the total row count first, then set page size to maximum before extracting

---

### 1A — Sales Transactions Report

**Navigate to:**
```
https://app.bridallive.com/app/reports/sales-transactions
```

**Set filters:**
- Status: **All** (do not filter by status — you need to see everything including drafts)
- Date range: use the period specified by the user, or default to **last 90 days** if not specified
- Click **Run Report**

**Wait for table to load**, then extract with:

```javascript
// Extract all sales transaction rows
const headers = Array.from(document.querySelectorAll('table thead th')).map(th => th.innerText.trim());
const rows = Array.from(document.querySelectorAll('table tbody tr')).map(tr =>
  Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())
);
JSON.stringify({ headers, rows });
```

**If the above selector returns empty**, try the BridalLive grid alternative:
```javascript
// Alternative for Angular/grid-based rendering
const rows = Array.from(document.querySelectorAll('[class*="row"], [class*="grid-row"], tr')).map(row =>
  Array.from(row.querySelectorAll('[class*="cell"], td')).map(c => c.innerText.trim()).filter(Boolean)
).filter(r => r.length > 2);
JSON.stringify(rows);
```

**Fields to capture per transaction:**
- Transaction ID / Order number
- Customer name
- Date
- Salesperson
- Transaction type (Sale, Layaway, etc.)
- Total amount
- Balance due
- Status (Open, Complete, Cancelled, etc.)

Store this as **SALES_DATA**.

---

### 1B — Special Orders / Purchase Orders Report

**Navigate to:**
```
https://app.bridallive.com/app/reports/purchase-orders
```

Alternatively try:
```
https://app.bridallive.com/app/purchaseorders
```

**Set filters:**
- Status: **All**
- Date range: same as Step 1A

**Extract with:**
```javascript
const headers = Array.from(document.querySelectorAll('table thead th')).map(th => th.innerText.trim());
const rows = Array.from(document.querySelectorAll('table tbody tr')).map(tr =>
  Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())
);
JSON.stringify({ headers, rows });
```

**Fields to capture per purchase order:**
- PO number
- Linked Sales Order / Transaction ID
- Customer name (if shown)
- Supplier / vendor
- Item description, style, size, colour
- Order date
- Expected delivery date
- Status (Draft, Ordered, Received, Cancelled)

Store this as **PO_DATA**.

---

### 1C — Layaway / Payment Report

**Navigate to:**
```
https://app.bridallive.com/app/reports/layaway
```

Alternatively:
```
https://app.bridallive.com/app/reports/payments
```

**Set filters:** All statuses, same date range.

**Extract with:**
```javascript
const headers = Array.from(document.querySelectorAll('table thead th')).map(th => th.innerText.trim());
const rows = Array.from(document.querySelectorAll('table tbody tr')).map(tr =>
  Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())
);
JSON.stringify({ headers, rows });
```

**Fields to capture:**
- Payment/Layaway ID
- Linked Transaction / Sales Order ID
- Customer name
- Payment amount
- Payment date
- Payment type (deposit, instalment, balance, etc.)
- Salesperson

Store this as **PAYMENT_DATA**.

---

### 1D — Inventory Receiving Report

**Navigate to:**
```
https://app.bridallive.com/app/reports/receiving
```

Alternatively:
```
https://app.bridallive.com/app/inventory/receiving
```

**Set filters:** All statuses, same date range.

**Extract with:**
```javascript
const headers = Array.from(document.querySelectorAll('table thead th')).map(th => th.innerText.trim());
const rows = Array.from(document.querySelectorAll('table tbody tr')).map(tr =>
  Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())
);
JSON.stringify({ headers, rows });
```

**Fields to capture:**
- Receiving record ID
- Linked PO number
- Linked Sales Order / Transaction ID
- Item description, style, size, colour
- Date received
- Received by (staff member)
- Quantity received

Store this as **RECEIVING_DATA**.

---

## STEP 2 — CROSS-REFERENCE AND IDENTIFY GAPS

With all four datasets collected, work through the following checks entirely in memory — no further browser calls needed at this stage.

### 2A — Payments with no Sales Order

Scan **PAYMENT_DATA**. For each payment record:
- Look up the linked Transaction/Sales Order ID in **SALES_DATA**
- If no matching Sales Order exists → **FLAG: Payment without Sales Order**
- If a Sales Order exists but status is "Cancelled" → **FLAG: Payment linked to cancelled order**

### 2B — Sales Orders requiring a Purchase Order but none exists

Scan **SALES_DATA** for open orders. For each open Sales Order:
- Check whether a matching record exists in **PO_DATA** (match on Transaction ID or customer name + approximate date)
- If no PO exists AND the item is not off-the-rack stock → **FLAG: Sales Order with no Purchase Order**
- Note: you cannot always determine from report data alone whether an item is stock or special order — flag any open Sales Order with no linked PO as **⚠️ NEEDS VERIFICATION** rather than a definite gap

### 2C — Purchase Orders not received

Scan **PO_DATA** for orders with status **Ordered** (not Received, not Cancelled):
- Check **RECEIVING_DATA** for a matching receiving record (match on PO number)
- If no receiving record exists AND the PO is older than **14 days** → **FLAG: PO overdue for receiving**
- If no receiving record exists AND the PO is less than 14 days old → **NOTE: PO pending — monitor**
- If a receiving record exists but the PO status in **PO_DATA** still shows "Ordered" → **FLAG: Received but not updated in system**

### 2D — Receiving records with no PO

Scan **RECEIVING_DATA**. For each receiving record:
- Look up the linked PO number in **PO_DATA**
- If no matching PO exists → **FLAG: Item received but no Purchase Order on record**

### 2E — Orphaned Sales Orders (no payment recorded)

Scan **SALES_DATA** for open orders with a balance due greater than zero:
- Check **PAYMENT_DATA** for any payment linked to this Sales Order
- If no payment exists at all → **FLAG: Sales Order with no deposit recorded**

---

## STEP 3 — DRILL INTO FLAGGED TRANSACTIONS (TARGETED NAVIGATION)

For each **CRITICAL** flag identified in Step 2, navigate to the individual transaction record to confirm the gap and collect additional detail before reporting.

This avoids false positives from report data that may be truncated or filtered.

**Navigate to a specific Sales Order:**
```
https://app.bridallive.com/app/transactions/[TRANSACTION_ID]
```

**On the transaction detail page**, extract key fields with:
```javascript
// Pull all labelled fields from the transaction detail view
const fields = {};
document.querySelectorAll('[class*="label"], [class*="field-label"], dt').forEach(label => {
  const value = label.nextElementSibling?.innerText?.trim() ||
                label.parentElement?.querySelector('[class*="value"], dd')?.innerText?.trim();
  if (label.innerText && value) fields[label.innerText.trim()] = value;
});

// Also extract line items
const lineItems = Array.from(document.querySelectorAll('[class*="line-item"], [class*="item-row"], tbody tr')).map(row =>
  Array.from(row.querySelectorAll('td, [class*="cell"]')).map(c => c.innerText.trim())
);

JSON.stringify({ fields, lineItems });
```

Confirm or dismiss each flag based on the detail view. Update your flag list accordingly.

**Navigate to a specific Purchase Order:**
```
https://app.bridallive.com/app/purchaseorders/[PO_ID]
```

Use the same JS extraction pattern on the PO detail page.

---

## STEP 4 — BUILD THE AUDIT REPORT

Produce the report in this format:

---

```
════════════════════════════════════════════════════════
BRIDALLIVE TRANSACTION AUDIT REPORT
Period: [date range]
Generated: [today's date]
Transactions reviewed: [N]
════════════════════════════════════════════════════════

SUMMARY
────────────────────────────────────────────────────────
❌ Critical issues:   [N]
⚠️  Needs verification: [N]
📋 Pending / monitor:  [N]
✅ Compliant:          [N]

════════════════════════════════════════════════════════
CRITICAL ISSUES — ACTION REQUIRED
════════════════════════════════════════════════════════

[ISSUE #1]
Customer:       [Name]
Transaction ID: [ID]
Issue:          [e.g. Payment of £300 recorded on 14/02/2025 — no Sales Order exists]
Salesperson:    [Name if known]
Recommended action: [e.g. Raise a Sales Order retrospectively and link the payment]
────────────────────────────────────────────────────────

[ISSUE #2]
...

════════════════════════════════════════════════════════
NEEDS VERIFICATION — POSSIBLE GAPS
════════════════════════════════════════════════════════

[ITEM #1]
Customer:       [Name]
Transaction ID: [ID]
Issue:          [e.g. Open Sales Order with no linked Purchase Order — unclear if stock item]
Action needed:  [e.g. Confirm with staff whether item is in stock or requires ordering]
────────────────────────────────────────────────────────

════════════════════════════════════════════════════════
PENDING / MONITOR
════════════════════════════════════════════════════════

[ITEM #1]
PO Number:      [ID]
Customer:       [Name]
Issue:          [e.g. Purchase Order placed 5 days ago — not yet received. Monitor.]
Expected:       [Expected delivery date if known]
────────────────────────────────────────────────────────

════════════════════════════════════════════════════════
NOTES
════════════════════════════════════════════════════════
[Any observations about patterns — e.g. "3 of the 4 critical issues involve the same salesperson"]
```

---

## STEP 5 — PRESENT AND CONFIRM

Present the full audit report to the user.

Then ask:
> "Would you like me to drill into any specific transaction, navigate to it in BridalLive, or export this report?"

Do **not** make any changes to BridalLive records without explicit user confirmation.

---

## EDGE CASES

**Report page URL is different to expected:**
BridalLive occasionally restructures its navigation. If a report URL returns a 404 or redirects to the dashboard, use the Reports menu instead:
```javascript
// Find all navigation links containing "report" or known report names
Array.from(document.querySelectorAll('a')).filter(a =>
  /report|purchase|receiving|layaway|transaction/i.test(a.innerText + a.href)
).map(a => ({ text: a.innerText.trim(), href: a.href }));
```
Use the results to locate the correct URLs and update your navigation accordingly.

**JavaScript extraction returns empty:**
BridalLive uses Angular rendering. If the DOM is not yet populated when JS runs, wait and retry:
```javascript
// Poll until rows appear (max 10 attempts)
await new Promise(resolve => {
  let attempts = 0;
  const interval = setInterval(() => {
    const rows = document.querySelectorAll('table tbody tr');
    if (rows.length > 0 || ++attempts >= 10) { clearInterval(interval); resolve(); }
  }, 500);
});
const rows = Array.from(document.querySelectorAll('table tbody tr')).map(tr =>
  Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())
);
JSON.stringify(rows);
```

**Report has pagination and no "show all" option:**
```javascript
// Check total record count if shown
document.querySelector('[class*="total"], [class*="count"], [class*="pagination"]')?.innerText?.trim();
```
If pagination cannot be removed, navigate to each page and append rows to your dataset before proceeding to Step 2.

**Transaction ID format unknown:**
BridalLive transaction IDs are typically numeric (e.g. `4821`). If the format differs, capture whatever identifier links records across reports — customer name + date can be used as a fallback match key.

---

## REFERENCES

See `references/audit-prompt.md` for the full BridalLive compliance audit prompt used to evaluate individual transactions in detail.
