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

    date_key = record["wedding_date"].strftime("%Y%m%d") if record["wedding_date"] else "99999999"
    return f"""
<div class="card" data-risk="{risk_key}" data-date="{date_key}" style="border-left:4px solid {r["border"]};background:{r["bg"]}">
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
        f'<button class="chip chip-{k}" data-filter="{k}" style="background:{RISK[k]["badge_bg"]}" aria-pressed="false">'
        f'<span class="chip-count">{counts[k]}</span> {RISK[k]["badge"]}</button>'
        for k in ["critical", "red", "amber", "ok"]
    ]
    return (
        '<div class="summary-strip">'
        + "".join(chips)
        + '<button class="chip chip-all" id="btn-all">All</button>'
        + '<select class="sort-select" id="sort-select">'
        + '<option value="asc">Date: Earliest first</option>'
        + '<option value="desc">Date: Latest first</option>'
        + '</select>'
        + '<span class="showing-count" id="showing-count"></span>'
        + "</div>"
    )


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
       background: #f4f6f8; color: #2d3436; }
.header { background: #2c3e50; color: #fff; padding: 20px 24px; }
.header h1 { font-size: 1.3rem; font-weight: 600; }
.header p  { font-size: 0.8rem; color: #b2bec3; margin-top: 4px; }
.summary-strip { display: flex; gap: 10px; padding: 16px 24px; background: #fff;
                 border-bottom: 1px solid #dfe6e9; flex-wrap: wrap; align-items: center; }
.chip { color: #fff; padding: 6px 16px; border-radius: 20px; border: 3px solid transparent;
        font-size: 0.8rem; font-weight: 600; cursor: pointer;
        transition: opacity 0.15s, transform 0.1s, border-color 0.1s; opacity: 0.55; }
.chip:hover { transform: scale(1.05); opacity: 0.85; }
.chip[aria-pressed="true"] { opacity: 1; border-color: #fff; box-shadow: 0 0 0 2px rgba(0,0,0,0.25); }
.chip-count { font-size: 1rem; }
.chip-all   { background: #2c3e50; margin-left: 4px; }
.sort-select { padding: 5px 10px; border-radius: 8px; border: 1px solid #dfe6e9;
               font-size: 0.8rem; color: #2d3436; background: #fff; cursor: pointer;
               margin-left: 4px; }
.showing-count { font-size: 0.8rem; color: #636e72; margin-left: 8px; }
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
.segment    { flex: 1; display: flex; align-items: flex-end; padding-bottom: 3px;
              justify-content: center; }
.seg-label  { font-size: 0.7rem; text-align: center; color: #2d3436; line-height: 1.25;
              font-weight: 500; }
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
<div class="cards" id="cards">
{cards_html}
</div>
<script>
(function () {{
  const chips = document.querySelectorAll('.chip[data-filter]');
  const btnAll = document.getElementById('btn-all');
  const sortSelect = document.getElementById('sort-select');
  const container = document.getElementById('cards');
  const showingCount = document.getElementById('showing-count');
  // active is the SET OF SELECTED filters. Empty = show all.
  const active = new Set();

  function allCards() {{
    return Array.from(container.querySelectorAll('.card'));
  }}

  function updateCount() {{
    const cards = allCards();
    const visible = cards.filter(function(c) {{ return !c.hidden; }}).length;
    showingCount.textContent = visible === cards.length ? '' : visible + ' shown';
  }}

  function applyFilter() {{
    allCards().forEach(function(card) {{
      card.hidden = active.size > 0 && !active.has(card.dataset.risk);
    }});
    chips.forEach(function(chip) {{
      chip.setAttribute('aria-pressed', active.has(chip.dataset.filter) ? 'true' : 'false');
    }});
    updateCount();
  }}

  function resetAll() {{
    active.clear();
    applyFilter();
  }}

  function applySort(order) {{
    const cards = allCards();
    cards.sort(function(a, b) {{
      const da = a.dataset.date, db = b.dataset.date;
      return order === 'asc' ? da.localeCompare(db) : db.localeCompare(da);
    }});
    cards.forEach(function(c) {{ container.appendChild(c); }});
  }}

  chips.forEach(function(chip) {{
    chip.addEventListener('click', function() {{
      const f = chip.dataset.filter;
      if (active.has(f)) {{ active.delete(f); }} else {{ active.add(f); }}
      applyFilter();
    }});
  }});

  btnAll.addEventListener('click', resetAll);

  sortSelect.addEventListener('change', function() {{
    applySort(sortSelect.value);
  }});

  updateCount();
}})();
</script>
</body>
</html>"""


def save_report(html_str: str, generated_at: datetime, directory: Path = HISTORY_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"report_{generated_at.strftime('%Y%m%d')}.html"
    path = directory / filename
    path.write_text(html_str, encoding="utf-8")
    # Always keep latest.html current so the web server has a stable URL
    (directory / "latest.html").write_text(html_str, encoding="utf-8")
    return path
