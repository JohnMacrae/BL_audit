"""Generate a standalone HTML thermometer report from CustomerRecord list."""

import html
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stitcher import CustomerRecord

HISTORY_DIR = Path(os.getenv("HISTORY_DIR", "/data/history"))

RISK = {
    "critical": {"border": "#c0392b", "bg": "#fdecea", "badge_bg": "#c0392b", "badge": "CRITICAL"},
    "red":      {"border": "#e74c3c", "bg": "#fdf0ef", "badge_bg": "#e74c3c", "badge": "AT RISK"},
    "amber":    {"border": "#f39c12", "bg": "#fef9ec", "badge_bg": "#f39c12", "badge": "WATCH"},
    "ok":       {"border": "#27ae60", "bg": "#edfaf1", "badge_bg": "#27ae60", "badge": "On Track"},
}

STAGE_LABELS = ["Enquiry", "Dress\nSelected", "Deposit\nPaid", "Ordered", "In Store", "Paid\nin Full"]

FILLED_COLOUR = "#27ae60"
EMPTY_COLOUR = "#dfe6e9"


def _esc(s: str) -> str:
    return html.escape(str(s) if s else "")


def _days_badge(days: int | None) -> str:
    if days is None:
        return '<span class="days-badge days-none">No date</span>'
    if days < 0:
        return f'<span class="days-badge days-past">{abs(days)}d ago</span>'
    if days < 30:
        colour = "#e74c3c"
    elif days < 60:
        colour = "#f39c12"
    else:
        colour = "#636e72"
    return f'<span class="days-badge" style="background:{colour}">{days} days</span>'


def _thermometer(stage: int) -> str:
    segments = []
    for i, label in enumerate(STAGE_LABELS, 1):
        filled = i <= stage
        colour = FILLED_COLOUR if filled else EMPTY_COLOUR
        label_lines = label.split("\n")
        label_html = "<br>".join(_esc(l) for l in label_lines)
        border_radius = ""
        if i == 1:
            border_radius = "border-radius:6px 0 0 6px;"
        elif i == 6:
            border_radius = "border-radius:0 6px 6px 0;"
        segments.append(
            f'<div class="segment" style="background:{colour};{border_radius}">'
            f'<div class="seg-label">{label_html}</div>'
            f'</div>'
        )
    return '<div class="thermometer">' + "".join(segments) + "</div>"


def _customer_card(record: "CustomerRecord") -> str:
    risk_key = record["risk_level"]
    r = RISK[risk_key]
    name = _esc(record["customer_name"])
    wedding = record["wedding_date"].strftime("%d/%m/%Y") if record["wedding_date"] else "Unknown"
    days_html = _days_badge(record["days_to_wedding"])
    badge = f'<span class="risk-badge" style="background:{r["badge_bg"]}">{r["badge"]}</span>'

    txn = record["active_dress_txn"]
    if txn:
        trx_info = f'<span class="trx-ref">{_esc(txn["trx_id"])} · {_esc(txn["items"][0]["item_name"] if txn["items"] else "")} · £{txn["trx_total"]:.0f}</span>'
    else:
        trx_info = '<span class="trx-ref trx-none">No dress transaction</span>'

    flags_html = ""
    if record["flags"]:
        flag_items = "".join(f'<li>&#9888; {_esc(f)}</li>' for f in record["flags"])
        flags_html = f'<ul class="flags">{flag_items}</ul>'

    return f"""
<div class="card" style="border-left:4px solid {r["border"]};background:{r["bg"]}">
  <div class="card-header">
    <div class="card-left">
      <span class="cust-name">{name}</span>
      {trx_info}
    </div>
    <div class="card-right">
      <span class="wedding-date">&#128141; {_esc(wedding)}</span>
      {days_html}
      {badge}
    </div>
  </div>
  {_thermometer(record["stage"])}
  {flags_html}
</div>"""


def _summary_strip(records: list) -> str:
    counts = {"critical": 0, "red": 0, "amber": 0, "ok": 0}
    for r in records:
        counts[r["risk_level"]] += 1
    chips = [
        f'<div class="chip chip-{k}" style="background:{RISK[k]["badge_bg"]}">'
        f'{counts[k]} {RISK[k]["badge"]}</div>'
        for k in ["critical", "red", "amber", "ok"]
    ]
    return '<div class="summary-strip">' + "".join(chips) + "</div>"


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
       background: #f4f6f8; color: #2d3436; }
.header { background: #2c3e50; color: #fff; padding: 20px 24px; }
.header h1 { font-size: 1.3rem; font-weight: 600; }
.header p  { font-size: 0.8rem; color: #b2bec3; margin-top: 4px; }
.summary-strip { display: flex; gap: 10px; padding: 16px 24px; background: #fff;
                 border-bottom: 1px solid #dfe6e9; flex-wrap: wrap; }
.chip { color: #fff; padding: 6px 16px; border-radius: 20px;
        font-size: 0.8rem; font-weight: 600; }
.cards { padding: 16px 24px; display: flex; flex-direction: column; gap: 12px;
         max-width: 960px; margin: 0 auto; }
.card { border-radius: 8px; padding: 14px 16px; }
.card-header { display: flex; justify-content: space-between; align-items: flex-start;
               flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.card-left  { display: flex; flex-direction: column; gap: 2px; }
.card-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cust-name  { font-size: 1rem; font-weight: 600; }
.trx-ref    { font-size: 0.75rem; color: #636e72; }
.trx-none   { font-style: italic; }
.wedding-date { font-size: 0.8rem; color: #636e72; }
.days-badge { color: #fff; padding: 3px 10px; border-radius: 12px;
              font-size: 0.75rem; font-weight: 600; }
.days-none  { background: #b2bec3; }
.days-past  { background: #636e72; }
.risk-badge { color: #fff; padding: 3px 10px; border-radius: 12px;
              font-size: 0.75rem; font-weight: 700; }
.thermometer { display: flex; gap: 2px; height: 36px; margin-bottom: 8px; }
.segment    { flex: 1; display: flex; align-items: flex-end; padding-bottom: 2px;
              justify-content: center; }
.seg-label  { font-size: 0.58rem; text-align: center; color: #636e72; line-height: 1.2; }
.flags      { list-style: none; margin-top: 4px; }
.flags li   { font-size: 0.78rem; color: #d35400; padding: 2px 0; }
@media print {
  .card { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .chip { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""


def generate_html(records: list, generated_at: datetime) -> str:
    ts = generated_at.strftime("%d %B %Y at %H:%M")
    total = len(records)
    cards_html = "".join(_customer_card(r) for r in records)
    summary = _summary_strip(records)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Serenity Brides — Customer Progress Report</title>
<style>{_CSS}</style>
</head>
<body>
<div class="header">
  <h1>Serenity Brides &amp; Rock Your Curves — Customer Progress</h1>
  <p>Generated: {_esc(ts)} &nbsp;|&nbsp; {total} brides (2026+)</p>
</div>
{summary}
<div class="cards">
{cards_html}
</div>
</body>
</html>"""


def save_report(html_str: str, generated_at: datetime, directory: Path = HISTORY_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"report_{generated_at.strftime('%Y%m%d')}.html"
    path = directory / filename
    path.write_text(html_str, encoding="utf-8")
    return path
