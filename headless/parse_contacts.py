"""Parse the BridalLive contacts CSV export into structured Contact records."""

import csv
import os
from datetime import date, datetime
from typing import TypedDict

CONTACTS_PATH = os.getenv("CONTACTS_PATH", "/data/contacts.csv")


class Contact(TypedDict):
    full_name: str      # "First Last" — matches Contact field in journal
    first_name: str
    last_name: str
    email: str
    mobile: str
    event_date: date | None
    status: str         # "A" = active


def _parse_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def normalise(name: str) -> str:
    return " ".join(name.strip().lower().split())


def load_contacts(path: str = CONTACTS_PATH, min_year: int = 2026) -> list:
    """
    Parse contacts CSV and filter to those with event_date year >= min_year.
    Returns list of Contact dicts sorted by event_date ascending;
    contacts with no date appended at end.
    """
    dated: list[Contact] = []
    undated: list[Contact] = []

    with open(path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            first = row.get("First Name", "").strip()
            last = row.get("Last Name", "").strip()
            full_name = f"{first} {last}".strip()
            event_date = _parse_date(row.get("Event Date", ""))

            if event_date is not None and event_date.year < min_year:
                continue

            contact: Contact = Contact(
                full_name=full_name,
                first_name=first,
                last_name=last,
                email=row.get("Email", "").strip(),
                mobile=(row.get("Mobile Phone", "") or row.get("Home Phone", "")).strip(),
                event_date=event_date,
                status=row.get("Status", "").strip(),
            )

            if event_date is not None:
                dated.append(contact)
            else:
                undated.append(contact)

    dated.sort(key=lambda c: c["event_date"])
    return dated + undated


def contacts_by_name(contacts: list) -> dict:
    """Return {normalised_full_name: Contact} for fast lookup."""
    return {normalise(c["full_name"]): c for c in contacts}
