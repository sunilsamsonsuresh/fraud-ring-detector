"""The medical records and the adjuster file of a claim.

Medical records: page 1 is the bill (services from the treatments table, and a short list of
recent visits, where a planted duplicate charge shows as a repeated line); page 2 is the
treatment history by month and the treating provider's summary.
Adjuster file: page 1 holds 6 to 12 dated note entries. Each entry starts with a date on its
own line; Python writes the dates, the LLM never does. Page 2 is the recorded statement.
"""

import datetime
import re

from src.data_generation.document_noise import (
    DATE_FORMATS,
    add_typos,
    format_date,
    maybe_blank_fields,
)
from src.data_generation.document_text_helpers import (
    as_date,
    checked_text,
    document_row,
    fake_person_name,
    person_name,
    person_role,
    with_facts,
    write_free_text,
)
from src.data_generation.pdf_layout import (
    INSURER_NAME,
    field_table,
    layout_for_id,
    line_item_table,
    make_layout,
    money,
    section_heading,
    text_block,
    title_block,
    write_pdf,
)
from src.data_generation.table_row_helpers import DATA_AS_OF_DATE

SERVICE_CODES = {
    "evaluation": "99203 New patient evaluation",
    "chiropractic adjustment": "98941 Spinal manipulation",
    "physical therapy": "97110 Therapeutic exercise",
    "massage therapy": "97124 Massage therapy",
    "imaging": "72040 X-ray, cervical spine",
    "pain management": "20552 Trigger point injection",
}
RECENT_VISITS_SHOWN = 6
ENTRY_MARKER = re.compile(r"Entry\s+(\d+)\s*:")
MIN_NOTE_ENTRIES = 6


def bill_rows(treatments):
    units, charges = {}, {}
    for visit in treatments:
        group = visit["procedure_group"]
        units[group] = units.get(group, 0) + 1
        charges[group] = charges.get(group, 0.0) + float(visit["charge"])
    rows = []
    for group, service_code in SERVICE_CODES.items():
        if group in units:
            rows.append([service_code, str(units[group]), money(charges[group])])
    return rows


def recent_visit_rows(treatments, duplicate_billing, layout, rng):
    rows = []
    for visit in treatments[-RECENT_VISITS_SHOWN:]:
        rows.append(
            [
                format_date(as_date(visit["visit_date"]), layout["date_format"]),
                SERVICE_CODES[visit["procedure_group"]],
                money(visit["charge"]),
            ]
        )
    if duplicate_billing == "Confirmed":
        rows.append(list(rows[-1]))  # the same service, date and charge again
    elif duplicate_billing == "Possible":
        rows.append(
            [
                rows[-1][0],
                "97112 Neuromuscular re-education",
                money(rng.uniform(90, 160)),
            ]
        )
    return rows


def history_rows(treatments):
    """One row per month: visits, services, charges. It shows how treatment grew or tapered."""
    months = {}
    for visit in treatments:
        month = visit["visit_date"][:7]
        entry = months.setdefault(month, {"visits": 0, "charge": 0.0, "groups": set()})
        entry["visits"] += 1
        entry["charge"] += float(visit["charge"])
        entry["groups"].add(visit["procedure_group"])
    rows = []
    for month in sorted(months):
        entry = months[month]
        month_name = datetime.date.fromisoformat(month + "-01").strftime("%B %Y")
        rows.append(
            [
                f"{month_name}: {', '.join(sorted(entry['groups']))}",
                str(entry["visits"]),
                money(entry["charge"]),
            ]
        )
    return rows


def make_medical_records(facts, rng, folder):
    claim, clinic, treatments = facts["claim"], facts["clinic"], facts["treatments"]
    layout = layout_for_id(clinic["provider_id"])
    header_lines = [
        clinic["street"],
        f"{clinic['city']}, {clinic['state']}",
        f"Phone {clinic['phone_number']}",
    ]
    bill_fields = maybe_blank_fields(
        [
            ("Patient", person_name(facts)),
            (
                "Date of birth",
                format_date(
                    as_date(facts["claimant"]["date_of_birth"]), layout["date_format"]
                ),
            ),
            ("Insurance claim", claim["claim_id"]),
            (
                "Date of injury",
                format_date(as_date(claim["loss_date"]), layout["date_format"]),
            ),
            (
                "First visit",
                format_date(
                    as_date(treatments[0]["visit_date"]), layout["date_format"]
                ),
            ),
            (
                "Last visit",
                format_date(
                    as_date(treatments[-1]["visit_date"]), layout["date_format"]
                ),
            ),
            ("Number of visits", str(len(treatments))),
        ],
        rng,
    )
    bill_page = title_block(
        clinic["name"], "Itemized Medical Bill", header_lines, layout
    )
    bill_page.append(field_table(bill_fields, layout))
    bill_page.append(section_heading("Services", layout))
    bill_page.append(
        line_item_table(
            ["Service", "Units", "Charge"],
            bill_rows(treatments)
            + [["TOTAL", "", money(claim["medical_bill_amount"])]],
            layout,
        )
    )
    bill_page.append(section_heading("Recent visits", layout))
    duplicate_billing = facts["profile"]["planted_features"].get("duplicate_billing")
    bill_page.append(
        line_item_table(
            ["Date", "Service", "Charge"],
            recent_visit_rows(treatments, duplicate_billing, layout, rng),
            layout,
        )
    )

    note = write_free_text(
        with_facts(
            f"Write a clinical treatment summary (about 150 words) by the treating provider for a patient with "
            f"{claim['injury_type']} after a {claim['accident_type']}. The patient had {len(treatments)} visits. "
            f"No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
            "medical_records",
            facts,
        ),
        rng,
    )
    note_page = title_block(
        clinic["name"], "Treatment History and Summary", header_lines, layout
    )
    note_page.append(
        field_table(
            [
                ("Patient", person_name(facts)),
                (
                    "Treating provider",
                    fake_person_name(f"clinician-{clinic['provider_id']}") + ", DC",
                ),
                ("Diagnosis", claim["injury_type"]),
            ],
            layout,
        )
    )
    note_page.append(section_heading("Treatment history by month", layout))
    note_page.append(
        line_item_table(
            ["Month and services", "Visits", "Charges"],
            history_rows(treatments),
            layout,
        )
    )
    note_page.append(section_heading("Treatment summary", layout))
    note_page.extend(text_block(note, layout))
    file_path = folder / f"{claim['claim_id']}_medical_records.pdf"
    return document_row(
        facts,
        "medical_records",
        file_path,
        write_pdf(file_path, [bill_page, note_page]),
    )


def note_dates(reported_date, entry_count, rng):
    """entry_count different dates after the report, at most 240 days later and not after the data date."""
    last_date = min(reported_date + datetime.timedelta(days=240), DATA_AS_OF_DATE)
    offsets = sorted(
        rng.sample(range(1, (last_date - reported_date).days + 1), entry_count)
    )
    return [reported_date + datetime.timedelta(days=offset) for offset in offsets]


def dated_entries(notes, dates, date_format, rng):
    """Turn 'Entry 1: text' blocks into 'DATE' + new line + text. Return (text, number of entries).
    Typos go into the entry text only, never into the marker or the date line."""
    parts = ENTRY_MARKER.split(notes)
    # parts = [text before, "1", entry 1 text, "2", entry 2 text, ...]
    entries = []
    for index in range(1, len(parts) - 1, 2):
        entry_text = " ".join(parts[index + 1].split())
        if entry_text and len(entries) < len(dates):
            entries.append(
                f"{format_date(dates[len(entries)], date_format)}\n{add_typos(entry_text, rng)}"
            )
    return "\n\n".join(entries), len(entries)


def make_adjuster_file(facts, rng, folder):
    claim = facts["claim"]
    layout = make_layout(0)
    layout["date_format"] = rng.choice(DATE_FORMATS)
    adjuster = fake_person_name(f"adjuster-{rng.randint(1, 6)}")
    represented = "is" if facts["attorney"] is not None else "is not"
    entry_count = rng.randint(6, 12)
    prompt = with_facts(
        f"Write {entry_count} short claim log entries (one to three sentences each) by an auto insurance "
        f"adjuster for a {claim['accident_type']} claim, in time order. Injury: {claim['injury_type']}. The "
        f"claimant {represented} represented by a lawyer. Start each entry on a new line with 'Entry 1:', "
        f"'Entry 2:' and so on. No names, dates or amounts. (Internal reference {claim['claim_id']}; do not "
        f"mention it.)",
        "adjuster_file",
        facts,
    )
    dates = note_dates(as_date(claim["reported_date"]), entry_count, rng)
    notes, found = dated_entries(
        checked_text(prompt, 2500), dates, layout["date_format"], rng
    )
    if found < MIN_NOTE_ENTRIES:
        retry_prompt = (
            prompt
            + f" You MUST write exactly {entry_count} entries, each starting with 'Entry N:'."
        )
        notes, found = dated_entries(
            checked_text(retry_prompt, 2500), dates, layout["date_format"], rng
        )
        if found < MIN_NOTE_ENTRIES:
            raise RuntimeError(
                f"The adjuster notes of {claim['claim_id']} have only {found} entries."
            )

    statement = write_free_text(
        f"Write a recorded statement transcript (about 250 words) between an insurance adjuster (lines "
        f"start with 'Q:') and the claimant (lines start with 'A:'). The claimant was the {person_role(facts)} "
        f"in a {claim['accident_type']} in {claim['loss_city']}, Texas, and has {claim['injury_type']}. "
        f"No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
        rng,
        max_tokens=1800,
    )
    statement_date = as_date(claim["reported_date"]) + datetime.timedelta(
        days=rng.randint(2, 10)
    )
    notes_page = title_block(
        INSURER_NAME, "Claim Notes", ["Bodily Injury Unit"], layout
    )
    notes_page.append(
        field_table(
            [
                ("Claim number", claim["claim_id"]),
                ("Claimant", person_name(facts)),
                ("Adjuster", adjuster),
            ],
            layout,
        )
    )
    notes_page.extend(text_block(notes, layout))
    statement_page = title_block(
        INSURER_NAME, "Recorded Statement", ["Bodily Injury Unit"], layout
    )
    statement_page.append(
        field_table(
            [
                ("Claim number", claim["claim_id"]),
                ("Statement of", person_name(facts)),
                ("Taken by", adjuster),
                ("Date", format_date(statement_date, layout["date_format"])),
            ],
            layout,
        )
    )
    statement_page.extend(text_block(statement.replace("\n", "\n\n"), layout))
    file_path = folder / f"{claim['claim_id']}_adjuster_file.pdf"
    return document_row(
        facts,
        "adjuster_file",
        file_path,
        write_pdf(file_path, [notes_page, statement_page]),
    )


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.make_medical_records_and_adjuster_file      (needs no Neo4j; the LLM texts come from the saved answers in data/cache/)
if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    from src.data_generation.generate_pdfs import (
        CLAIM_DOCUMENT_BUILDERS,
        facts_for_one_claim,
    )

    facts, rng = facts_for_one_claim("C-1001")
    folder = Path(tempfile.mkdtemp())
    # The adjuster notes depend on the random numbers drawn by the builders before it.
    # So we call the builders in the same order as generate_pdfs.py. Then the saved LLM answers fit.
    for builder in CLAIM_DOCUMENT_BUILDERS:
        row = builder(facts, rng, folder)
        if builder in (make_medical_records, make_adjuster_file):
            print(builder.__name__, "->", row)
    print("note_dates (6 entries):", note_dates(datetime.date(2024, 3, 1), 6, rng))
    print("PDFs are in", folder)
