"""Convert the curated provider coverage matrix (xlsx) into data/providers.json.

The spreadsheet is the human-verified source of truth. This script only
normalizes it; it never adds facts that are not in the sheet.

Usage:
    cd backend && uv run python ../scripts/import_providers.py path/to/matrix.xlsx
"""

import json
import re
import sys
from pathlib import Path

import openpyxl
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "providers.json"

CATEGORY_MAP = {
    "Water Damage": "water_damage_restoration",
    "Plumbing": "plumbing",
    "HVAC": "hvac",
    "Electrical": "electrical",
    "Roofing": "roofing",
}
AREA_COLUMNS = {
    "Santa Clara": "santa_clara",
    "Sunnyvale": "sunnyvale",
    "North San Jose": "north_san_jose",
}
VALID_COVERAGE = {"verified", "provisional", "unknown", "out_of_area"}
# Only claim 24/7 when the cited evidence text says so explicitly.
EMERGENCY_PATTERN = re.compile(r"24/7|open 24 hours|emergency", re.IGNORECASE)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 10:
        raise ValueError(f"unexpected phone format: {raw!r}")
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def parse_city_zip(address: str) -> tuple[str | None, str | None]:
    match = re.search(r"([A-Za-z .]+),\s*CA\s*(\d{5})?", address or "")
    if not match:
        return None, None
    city = match.group(1).split(",")[-1].strip()
    return city, match.group(2)


def main(xlsx_path: str) -> None:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Provider Matrix"]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() for h in rows[0]]
    verified_at = None
    for row in wb["Coverage Summary"].iter_rows(values_only=True):
        if row[0] == "verified_at":
            verified_at = str(row[1])

    providers = []
    for raw in rows[1:]:
        if not any(raw):
            continue
        rec = dict(zip(header, raw))
        coverage = {}
        for col, key in AREA_COLUMNS.items():
            status = str(rec[col]).strip().lower()
            if status not in VALID_COVERAGE:
                raise ValueError(f"{rec['Provider']}: bad coverage {status!r} for {col}")
            coverage[key] = status
        address = (rec["Address"] or "").strip() or None
        city, zip_code = parse_city_zip(address or "")
        evidence = rec["Evidence / rationale"].strip()
        providers.append(
            {
                "id": slugify(rec["Provider"]),
                "name": rec["Provider"].strip(),
                "service_categories": [CATEGORY_MAP[rec["Category"].strip()]],
                "address": address,
                "city": city,
                "zip_code": zip_code,
                "phone": normalize_phone(str(rec["Phone"])),
                "website": "{0.scheme}://{0.netloc}".format(urlsplit(rec["Primary source URL"].strip())),
                "coverage": coverage,
                "coverage_evidence": evidence,
                "emergency_service": True if EMERGENCY_PATTERN.search(evidence) else None,
                "source_url": rec["Primary source URL"].strip(),
                "source_type": rec["Source type"],
                "implementation_note": rec["Implementation note"],
                "verified_at": verified_at,
            }
        )

    ids = [p["id"] for p in providers]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate provider ids")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(providers, indent=2) + "\n")
    print(f"wrote {len(providers)} providers -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1])
