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
