# BridalLive Audit Skill — Handover to Claude Code

## What this folder contains

```
bridallive-audit-skill/
├── HANDOVER.md                        ← this file
├── SKILL.md                           ← the Claude-in-Chrome skill (navigation + JS extraction)
└── references/
    └── audit-prompt.md                ← the compliance evaluation prompt (per-transaction logic)
```

---

## What was built and why

Julie's bridal boutique (Serenity Brides) runs BridalLive as its POS. Following a manager departure, staff have not been consistently following the correct transaction workflow. The specific problem is:

- Sales are being taken (payments recorded, deposits collected) **without a proper Sales Order being raised**
- Where items need to be ordered from a supplier, **Purchase Orders are not always being created or linked**
- Items arriving from suppliers are **not always being received and recorded** in BridalLive
- This creates orphaned records, untracked stock, and revenue recognition problems

Two artefacts were built in this session to address this:

### 1. `SKILL.md` — The browser automation skill

This is a **Claude-in-Chrome skill** that drives the BridalLive web interface at `app.bridallive.com`. It:

1. Checks whether BridalLive is already open and logged in — navigates there if not, halts cleanly if login is required
2. Navigates four report pages in sequence and extracts all data using **JavaScript injection** (not screenshotting or clicking through rows individually):
   - Sales Transactions report
   - Purchase Orders / Special Orders report
   - Layaway / Payments report
   - Inventory Receiving report
3. Cross-references all four datasets in memory to identify compliance gaps
4. Drills into individual transaction detail pages only for confirmed critical flags (to avoid false positives from truncated report data)
5. Produces a structured audit report categorised as: Critical / Needs Verification / Pending / Compliant

The JS-injection-first approach was chosen based on prior experience with BridalLive — it is faster and more reliable than UI interaction for bulk data extraction from its Angular-rendered tables.

### 2. `references/audit-prompt.md` — The per-transaction evaluation prompt

This is a **system prompt** for evaluating individual transactions in detail. It defines the correct BridalLive workflow (7 stages from consultation through to completion) and provides a structured checklist covering:
- Sales Order check
- Purchase Order / Special Order check
- Receiving check
- Order completion check

It produces a per-transaction finding with severity ratings (CRITICAL / MODERATE / MINOR) and recommended actions. Tone is constructive — findings are framed as process gaps, suitable for sharing with staff.

The skill (`SKILL.md`) references this prompt for detailed per-transaction evaluation after bulk data is collected.

---

## How to deploy

### Option A — As a Claude-in-Chrome skill (intended use)

Copy the entire `bridallive-audit-skill/` folder to:
```
/mnt/skills/user/bridallive-audit/
```

Claude in Chrome will then trigger this skill when it detects phrases like:
- "audit BridalLive"
- "check the girls' transactions"
- "are special orders being recorded correctly"
- "find missing purchase orders"

### Option B — As a Claude Code task

If running from Claude Code directly (e.g. as part of a scheduled audit or OB1 task), the SKILL.md steps can be executed using the browser tools available in Claude Code. The same JS extraction patterns apply.

---

## What needs calibrating on first run

BridalLive uses Angular routing and the exact URLs and CSS selectors **must be verified against the live instance** on first run. The skill includes fallback handlers for both, but a human-assisted first run is recommended to confirm:

1. **Report URLs** — the skill attempts these in order:
   - `https://app.bridallive.com/app/reports/sales-transactions`
   - `https://app.bridallive.com/app/reports/purchase-orders`
   - `https://app.bridallive.com/app/reports/layaway`
   - `https://app.bridallive.com/app/reports/receiving`
   
   If any redirect to the dashboard, the skill will fall back to scanning the navigation menu for correct links via JS. Capture the correct URLs and update the skill.

2. **Table selectors** — the skill tries `table tbody tr / td` first, then Angular grid class variants. On first run, confirm which selector pattern BridalLive uses and note it.

3. **Transaction detail URL pattern** — assumed to be `https://app.bridallive.com/app/transactions/[ID]`. Confirm by clicking through to one transaction manually and checking the URL.

4. **PO detail URL pattern** — assumed to be `https://app.bridallive.com/app/purchaseorders/[ID]`. Confirm similarly.

Once confirmed, update the relevant sections of `SKILL.md` to hardcode the correct values and remove the fallback logic if no longer needed.

---

## Known limitations

- The skill cannot determine from report data alone whether a Sales Order item is a **special order or an off-the-rack stock item**. Open Sales Orders with no linked PO are flagged as "Needs Verification" rather than "Critical" for this reason — a human must confirm.
- If BridalLive report pages have **no "show all rows" option**, the skill will paginate through pages and concatenate results. This increases tool call count — flag to user if the report is very large.
- The skill does **not write back to BridalLive** — it is read-only. Any corrective actions must be taken manually or via a separate workflow.

---

## Related context

- BridalLive account: `app.bridallive.com` — Serenity Brides / Weddings By Design EA Ltd
- Julie's business; managed by John Macrae
- Prior BridalLive work in Claude sessions includes the "Cancelled Order £0 item" technique for ghost/stale special orders, and the Layaway Batch completion method (coordinate clicks at [1490,497] → [1000,153])
- sbbrain (Julie's Life Engine instance) is at `/volume1/docker/sbbrain/` on the NAS — open BridalLive cases can eventually be pushed as thoughts to sbbrain once the audit workflow is validated

---

*Handover written: May 2026*
*Session: Claude.ai chat — BridalLive audit skill build*
