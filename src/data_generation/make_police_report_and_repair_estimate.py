"""The police report and the repair estimate of a claim.

Police report: the report number, time and officer come from the INCIDENT, so every claimant
of one accident gets the same header. A table lists the occupants of each vehicle: the
number of occupants of the insured car is the planted occupants_listed (AS-6). Claimants who
were not really in the car are listed last, so they are the ones left off.
Repair estimate: the labor hours follow the planted labor_hours_plausibility, and a confirmed
duplicate charge shows as one part listed twice. The total always equals the table amount.
"""

import datetime
import random

from src.data_generation.document_noise import format_date, maybe_blank_fields
from src.data_generation.document_text_helpers import (
    as_date,
    document_row,
    fake_person_name,
    person_name,
    person_role,
    split_amount,
    with_facts,
    write_free_text,
)
from src.data_generation.pdf_layout import (
    POLICE_AGENCY_NAME,
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

# Dollars per labor hour: a lower rate turns the same labor amount into more hours.
LABOR_RATE_BY_RATING = {"Plausible": 68, "Elevated": 48, "Excessive": 22}
LISTED_LAST = ["Added later", "Not present"]


def occupant_rows(facts, rng):
    """Rows (vehicle, seat, name) for the occupants table."""
    listed = []
    later = []
    for other_claim in facts["incident_claims"]:
        profile = facts["profiles"][other_claim["claim_id"]]
        name = f"{other_claim['first_name']} {other_claim['last_name']}"
        if profile["planted_features"].get("occupant_presence") in LISTED_LAST:
            later.append(name)
        else:
            listed.append(name)
    names = (listed + later)[: facts["profile"]["planted_features"]["occupants_listed"]]
    while len(names) < facts["profile"]["planted_features"]["occupants_listed"]:
        names.append(
            fake_person_name(f"occupant-{facts['claim']['incident_id']}-{len(names)}")
        )
    rows = []
    for seat_number, name in enumerate(names):
        rows.append(
            [
                "Vehicle 1 (insured)",
                "Driver" if seat_number == 0 else f"Passenger {seat_number}",
                name,
            ]
        )
    rows.append(
        [
            "Vehicle 2",
            "Driver",
            fake_person_name(f"other-driver-{facts['claim']['incident_id']}"),
        ]
    )
    if rng.random() < 0.3:
        rows.append(
            [
                "Vehicle 2",
                "Passenger 1",
                fake_person_name(f"other-passenger-{facts['claim']['incident_id']}"),
            ]
        )
    return rows


def make_police_report(facts, rng, folder):
    if not facts["profile"]["has_police_report"]:
        return None
    claim, vehicle = facts["claim"], facts["vehicle"]
    layout = make_layout(3)
    incident_rng = random.Random(
        f"{facts['seed']}-{claim['incident_id']}"
    )  # same header for the whole incident
    officer_number = incident_rng.randint(1, 40)
    report_number = f"TR-{claim['loss_date'][:4]}-{incident_rng.randint(10000, 99999)}"
    crash_time = f"{incident_rng.randint(6, 21):02d}:{incident_rng.randint(0, 59):02d}"
    narrative = write_free_text(
        with_facts(
            f"Write a police officer's crash report narrative (about 150 words). Collision type: "
            f"{claim['accident_type']} in {claim['loss_city']}, Texas. The claimant was a {person_role(facts)} "
            f"and reported {claim['injury_type']}. Refer to people as Driver 1, Driver 2 or Passenger. "
            f"No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
            "police_report",
            facts,
        ),
        rng,
    )
    fields = maybe_blank_fields(
        [
            ("Report number", report_number),
            # police_loss_date is the real loss date, except where a conflict was planted (AS-7).
            (
                "Crash date",
                format_date(facts["police_loss_date"], layout["date_format"]),
            ),
            ("Crash time", crash_time),
            ("Location", claim["location_text"]),
            ("Collision type", claim["accident_type"]),
            ("Involved person", f"{person_name(facts)} ({person_role(facts)})"),
            ("Phone", facts["claimant"]["phone_number"]),
            ("Vehicle", f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"),
            ("License plate", vehicle["license_plate"]),
            ("Injuries reported", claim["injury_type"]),
            (
                "Investigating officer",
                f"Officer {fake_person_name(f'officer-{officer_number}')}, Badge {1000 + officer_number}",
            ),
        ],
        rng,
    )
    page = title_block(POLICE_AGENCY_NAME, "Crash Report", ["Records Section"], layout)
    page.append(field_table(fields, layout))
    page.append(section_heading("Occupants of each vehicle", layout))
    page.append(
        line_item_table(["Vehicle", "Seat", "Name"], occupant_rows(facts, rng), layout)
    )
    page.append(section_heading("Officer's narrative", layout))
    page.extend(text_block(narrative, layout))
    file_path = folder / f"{claim['claim_id']}_police_report.pdf"
    return document_row(facts, "police_report", file_path, write_pdf(file_path, [page]))


def make_repair_estimate(facts, rng, folder):
    shop = facts["repair_shop"]
    if shop is None:
        return None
    claim, vehicle = facts["claim"], facts["vehicle"]
    features = facts["profile"]["planted_features"]
    layout = layout_for_id(shop["provider_id"])
    if claim["accident_type"] == "rear-end collision":
        part_names = rng.sample(
            [
                "Rear bumper cover",
                "Rear bumper reinforcement",
                "Trunk lid",
                "Left tail lamp assembly",
                "Right tail lamp assembly",
                "Rear body panel",
            ],
            3,
        )
    else:
        part_names = rng.sample(
            [
                "Front bumper cover",
                "Left front fender",
                "Right front door shell",
                "Headlamp assembly",
                "Hood panel",
                "Left quarter panel",
            ],
            3,
        )
    duplicate = features.get("duplicate_billing") == "Confirmed"
    shares = [rng.uniform(0.12, 0.2), rng.uniform(0.1, 0.18), rng.uniform(0.08, 0.15)]
    if duplicate:
        shares.append(shares[0])  # the first part again, for the same amount
    shares.extend([rng.uniform(0.25, 0.35), rng.uniform(0.12, 0.2)])
    amounts = split_amount(claim["repair_estimate_amount"], shares)
    part_rows = list(
        zip(part_names + ([part_names[0]] if duplicate else []), amounts[:-2])
    )
    rows = [[part_name, "1", money(amount)] for part_name, amount in part_rows]
    labor_rate = LABOR_RATE_BY_RATING[
        features.get("labor_hours_plausibility", "Plausible")
    ]
    rows.append(
        ["Body labor", f"{amounts[-2] / labor_rate:.1f} hrs", money(amounts[-2])]
    )
    rows.append(["Paint and materials", "", money(amounts[-1])])
    rows.append(["TOTAL", "", money(claim["repair_estimate_amount"])])

    remarks = write_free_text(
        with_facts(
            f"Write the appraiser's remarks (about 80 words) on a body shop repair estimate after a "
            f"{claim['accident_type']}. Describe the damage seen on the vehicle and the repair plan. No names, "
            f"dates or amounts. (Internal reference {claim['claim_id']}; do not mention it.)",
            "repair_estimate",
            facts,
        ),
        rng,
    )
    estimate_date = as_date(claim["loss_date"]) + datetime.timedelta(
        days=rng.randint(2, 12)
    )
    fields = maybe_blank_fields(
        [
            ("Estimate number", f"EST-{rng.randint(100000, 999999)}"),
            ("Estimate date", format_date(estimate_date, layout["date_format"])),
            ("Customer", person_name(facts)),
            ("Phone", facts["claimant"]["phone_number"]),
            ("Insurance claim", claim["claim_id"]),
            ("Vehicle", f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"),
            ("VIN", vehicle["vin"]),
            ("License plate", vehicle["license_plate"]),
        ],
        rng,
    )
    page = title_block(
        shop["name"],
        "Repair Estimate",
        [
            shop["street"],
            f"{shop['city']}, {shop['state']}",
            f"Phone {shop['phone_number']}",
        ],
        layout,
    )
    page.append(field_table(fields, layout))
    page.append(section_heading("Estimate details", layout))
    page.append(line_item_table(["Description", "Qty / Hours", "Amount"], rows, layout))
    page.append(section_heading("Appraiser remarks", layout))
    page.extend(text_block(remarks, layout))
    file_path = folder / f"{claim['claim_id']}_repair_estimate.pdf"
    return document_row(
        facts, "repair_estimate", file_path, write_pdf(file_path, [page])
    )


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.make_police_report_and_repair_estimate      (needs no Neo4j; the LLM texts come from the saved answers in data/cache/)
if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    from src.data_generation.generate_pdfs import facts_for_one_claim

    facts, rng = facts_for_one_claim("C-1001")
    folder = Path(tempfile.mkdtemp())
    print(
        "1. make_police_report:",
        make_police_report(facts, rng, folder),
        "(None = no police report)",
    )
    print(
        "2. make_repair_estimate:",
        make_repair_estimate(facts, rng, folder),
        "(None = no repair shop)",
    )
    print("PDFs are in", folder)
