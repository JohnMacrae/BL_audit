# BL_Audit — SSH Handoff

Picking up from a Windows Claude Code session. All work is in the GitHub repo.

---

## Repo

```
https://github.com/JohnMacrae/BL_audit
```

Token and remote URL are stored in the local git config on the NAS at:
```
/volume1/docker/BL_Audit/.git/config
```

To clone fresh on the NAS if needed:
```bash
git clone https://TOKEN@github.com/JohnMacrae/BL_audit.git /volume1/docker/BL_Audit
```
(Token is in git-config.txt in the project folder, or ask Claude for it.)

---

## What's been built

```
BL_Audit/
├── HANDOVER.md          — original context (what this is, why it exists)
├── SKILL.md             — the Claude-in-Chrome browser skill (reference)
├── audit-prompt.md      — per-transaction evaluation prompt (reference)
└── headless/
    ├── audit.py         — Playwright headless audit script
    ├── Dockerfile       — mcr.microsoft.com/playwright/python base image
    ├── compose.yml      — mounts gmail_client.py + token from NAS paths
    ├── .env             — BridalLive credentials + Gmail config (NOT in git)
    └── test_audit.py    — pytest suite for cross_reference() and format_report()
```

---

## Immediate task — fix tests so they run

**Problem:** `test_audit.py` imports `audit.py`, which has a top-level
`from playwright.async_api import async_playwright`. This means tests fail
unless Playwright is installed — which it won't be outside Docker.

**Fix:** Split `audit.py` into two files:

- `audit_logic.py` — pure Python: `cross_reference()`, `format_report()`, `build_report()`, helper functions. No Playwright, no Gmail.
- `audit.py` — thin runner: imports `audit_logic`, handles Playwright browser setup, login, page navigation, calls gmail_client.

Then update `test_audit.py` to `import audit_logic` instead of `import audit`.

Tests should then run with just:
```bash
pip install pytest
python -m pytest headless/test_audit.py -v
```

---

## Run the audit (once tests pass)

```bash
cd /volume1/docker/BL_Audit/headless
docker compose run --rm bl-audit
```

First run builds the image (slow — Playwright + Chromium). Subsequent runs are fast.

**The .env file is not in git.** Create it at `/volume1/docker/BL_Audit/headless/.env`:
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

## Gmail wiring

The compose.yml mounts these NAS paths into the container:
```
/volume1/docker/gmail-mcp/gmail_client.py  →  /gmail/gmail_client.py
/volume1/docker/gmail-mcp/config/jramacrae →  /gmail-config/
```

The script calls:
```python
gc = GmailClient()
gc.send_email(to=RECIPIENT, subject=..., body=...)
```

**Verify the GmailClient signature before first run** — check
`/volume1/docker/gmail-mcp/gmail_client.py` to confirm the constructor
and `send_email` method match what audit.py expects. Adjust if needed.

---

## Known gaps to address after first real run

1. **Report URLs** — BridalLive's Angular routing may differ. The script tries
   two URLs per report and falls back to nav scanning. Capture the correct URLs
   on first run and hardcode them.

2. **Table selectors** — JS injection tries standard `table tbody tr` then
   Angular grid class variants. Confirm which works and remove the fallback.

3. **Transaction ID format** — assumed numeric (e.g. `4821`). Verify on first run.

4. **GmailClient.send_email signature** — see above.

---

## Project context

- Serenity Brides / Weddings By Design EA Ltd — Julie's bridal boutique
- BridalLive at app.bridallive.com
- Purpose: audit staff compliance with the correct sales workflow after a manager departure
- This project is completely separate from the property management stack (property-agent, sbbrain, etc.)
