"""Make the PDFs in one claim file: FNOL, police report, repair estimate,
medical bill with treatment note, attorney letter, adjuster notes with
recorded statement (PLAN.md A4).

Python fills every name, date, ID and amount from the tables.
The LLM writes only free text, and the prompts ask it not to add names,
dates or amounts. Each builder returns one row for documents.csv, or None
when the claim does not have that document.
"""

import datetime
import re
import threading

from faker import Faker

from src import config
from src.datagen.noise import DATE_FORMATS, add_typos, format_date, maybe_blank_fields
from src.datagen.templates import (
    INSURER_NAME, POLICE_AGENCY_NAME, field_table, layout_for_id, line_item_table,
    make_layout, money, section_heading, text_block, title_block, write_pdf,
)
from src.llm import ask_llm

SYSTEM_PROMPT = (
    "You write short, realistic text for SYNTHETIC (fake) auto insurance documents that are used "
    "to test software. Everything is fictional. Write plain text only: no markdown, no headings, "
    "no bullet symbols. Do not invent names of people or companies, dates, phone numbers or money "
    "amounts. Use a placeholder in square brackets only when the request asks for it."
)

# Ring texts have no claim reference, so every ring claim gets the same cached text.
RING_A_STORY_PROMPT = (
    "Write a first-person account (about 120 words) by a driver for an insurance claim form. "
    "The car in front stopped suddenly for no clear reason and the driver could not avoid a "
    "rear-end collision; the driver felt neck and back pain soon after. Use the exact placeholder "
    "[LOSS_DATE] for the date and [CITY] for the city. No names."
)
RING_B_NOTE_PROMPT = (
    "Write a clinical treatment summary (about 150 words) by a chiropractor for a patient with "
    "neck and back strain after a car accident. Use the exact placeholder [VISITS] for the number "
    "of visits. Describe a standard plan of spinal adjustments, therapeutic exercise and electrical "
    "stimulation, and say the patient reached maximum improvement. No names, no dates."
)

# Free text must not contain placeholders like [CLAIMANT NAME]: no code would fill them.
UNWANTED_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z_ ]+\]")

# Shared ring texts use a fixed max_tokens, so every caller makes the same cache key.
RING_TEMPLATE_MAX_TOKENS = 1500

_name_faker = Faker("en_US")
# Seeding and then reading must happen together. Without the lock, two threads
# could seed one after the other and one of them would get the wrong name.
_name_faker_lock = threading.Lock()


def fake_person_name(key):
    """The same key always gives the same name (for example, one doctor per clinic)."""
    with _name_faker_lock:
        _name_faker.seed_instance(key)
        return f"{_name_faker.first_name()} {_name_faker.last_name()}"


def get_ring_template(prompt):
    """Return a shared ring text, with placeholders still in it."""
    return ask_llm(prompt, config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, RING_TEMPLATE_MAX_TOKENS)


def as_date(iso_text):
    return datetime.date.fromisoformat(iso_text)


def write_free_text(prompt, rng, max_tokens=1200):
    text = ask_llm(prompt, config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, max_tokens)
    if UNWANTED_PLACEHOLDER.search(text):
        # The model sometimes invents its own placeholder, such as [CLAIMANT NAME].
        # Ask once more with a stricter prompt; that is a new request with its own cache entry.
        stricter_prompt = prompt + " Never use square brackets or placeholders of any kind."
        text = ask_llm(stricter_prompt, config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, max_tokens)
        if UNWANTED_PLACEHOLDER.search(text):
            raise RuntimeError(f"The model still wrote a placeholder: {UNWANTED_PLACEHOLDER.search(text).group()}")
    return add_typos(text, rng)


def fill_placeholders(text, replacements):
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def split_amount(total, shares):
    """Split `total` in proportion to `shares`. The parts add up to the exact cent."""
    total_cents = round(float(total) * 100)
    share_sum = sum(shares)
    parts_in_cents = []
    for share in shares[:-1]:
        parts_in_cents.append(int(total_cents * share / share_sum))
    parts_in_cents.append(total_cents - sum(parts_in_cents))
    return [cents / 100 for cents in parts_in_cents]


def document_row(facts, document_type, file_path, page_count):
    claim_id = facts["claim"]["claim_id"]
    return {"document_id": f"{claim_id}-{document_type}", "claim_id": claim_id,
            "document_type": document_type, "file_name": file_path.name, "page_count": page_count}


def person_name(facts):
    return f"{facts['claimant']['first_name']} {facts['claimant']['last_name']}"


def person_role(facts):
    return "passenger" if facts["claim"]["repair_shop_id"] == "" else "driver"


def make_fnol(facts, rng, folder):
    claim, claimant, address, vehicle = facts["claim"], facts["claimant"], facts["address"], facts["vehicle"]
    layout = make_layout(0)
    layout["date_format"] = rng.choice(DATE_FORMATS)
    loss_date_text = format_date(as_date(claim["loss_date"]), layout["date_format"])

    if facts["ring_id"] == "A":
        template = get_ring_template(RING_A_STORY_PROMPT)
        story = fill_placeholders(template, {"[LOSS_DATE]": loss_date_text, "[CITY]": claim["loss_city"]})
        story = add_typos(story, rng)
    else:
        story = write_free_text(
            f"Write a first-person account (about 120 words) by the {person_role(facts)} for an insurance "
            f"claim form. Accident: {claim['accident_type']} in {claim['loss_city']}, Texas. Injury: "
            f"{claim['injury_type']}. No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
            rng,
        )

    fields = maybe_blank_fields([
        ("Claim number", claim["claim_id"]),
        ("Date reported", format_date(as_date(claim["reported_date"]), layout["date_format"])),
        ("Date of loss", loss_date_text),
        ("Loss location", f"{claim['loss_city']}, TX"),
        ("Type of accident", claim["accident_type"]),
        ("Claimant name", person_name(facts)),
        ("Claimant role", person_role(facts)),
        ("Date of birth", format_date(as_date(claimant["date_of_birth"]), layout["date_format"])),
        ("Street address", address["street"]),
        ("City / State", f"{address['city']}, {address['state']}"),
        ("ZIP code", address["zip_code"]),
        ("Phone", claimant["phone_number"]),
        ("Policy number", claim["policy_id"]),
        ("Vehicle", f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"),
        ("VIN", vehicle["vin"]),
        ("License plate", vehicle["license_plate"]),
        ("Reported injury", claim["injury_type"]),
    ], rng)
    page = title_block(INSURER_NAME, "First Notice of Loss (FNOL)", ["Claims Department - Houston Service Center"], layout)
    page.append(field_table(fields, layout))
    page.append(section_heading("Description of the accident (claimant's words)", layout))
    page.extend(text_block(story, layout))
    file_path = folder / f"{claim['claim_id']}_fnol.pdf"
    return document_row(facts, "fnol", file_path, write_pdf(file_path, [page]))


def make_police_report(facts, rng, folder):
    if not facts["has_police_report"]:
        return None
    claim, vehicle = facts["claim"], facts["vehicle"]
    layout = make_layout(3)
    officer_number = rng.randint(1, 40)
    narrative = write_free_text(
        f"Write a police officer's crash report narrative (about 120 words). Collision type: "
        f"{claim['accident_type']} in {claim['loss_city']}, Texas. The claimant was a {person_role(facts)} "
        f"and reported {claim['injury_type']}. Refer to people as Driver 1, Driver 2 or Passenger. "
        f"No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
        rng,
    )
    fields = maybe_blank_fields([
        ("Report number", f"TR-{claim['loss_date'][:4]}-{rng.randint(10000, 99999)}"),
        # police_loss_date is usually the real loss date; for a few claims it is planted wrong.
        ("Crash date", format_date(facts["police_loss_date"], layout["date_format"])),
        ("Crash time", f"{rng.randint(6, 21):02d}:{rng.randint(0, 59):02d}"),
        ("Location", f"{claim['loss_city']}, TX"),
        ("Collision type", claim["accident_type"]),
        ("Involved person", f"{person_name(facts)} ({person_role(facts)})"),
        ("Phone", facts["claimant"]["phone_number"]),
        ("Vehicle", f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"),
        ("License plate", vehicle["license_plate"]),
        ("Injuries reported", claim["injury_type"]),
        ("Investigating officer", f"Officer {fake_person_name(f'officer-{officer_number}')}, Badge {1000 + officer_number}"),
    ], rng)
    page = title_block(POLICE_AGENCY_NAME, "Crash Report", ["Records Section"], layout)
    page.append(field_table(fields, layout))
    page.append(section_heading("Officer's narrative", layout))
    page.extend(text_block(narrative, layout))
    file_path = folder / f"{claim['claim_id']}_police_report.pdf"
    return document_row(facts, "police_report", file_path, write_pdf(file_path, [page]))


def make_repair_estimate(facts, rng, folder):
    shop = facts["repair_shop"]
    if shop is None:
        return None
    claim, vehicle = facts["claim"], facts["vehicle"]
    layout = layout_for_id(shop["provider_id"])
    if claim["accident_type"] == "rear-end collision":
        part_names = rng.sample(["Rear bumper cover", "Rear bumper reinforcement", "Trunk lid",
                                 "Left tail lamp assembly", "Right tail lamp assembly", "Rear body panel"], 3)
    else:
        part_names = rng.sample(["Front bumper cover", "Left front fender", "Right front door shell",
                                 "Headlamp assembly", "Hood panel", "Left quarter panel"], 3)
    shares = [rng.uniform(0.12, 0.2), rng.uniform(0.1, 0.18), rng.uniform(0.08, 0.15),
              rng.uniform(0.25, 0.35), rng.uniform(0.12, 0.2)]
    amounts = split_amount(claim["repair_estimate_amount"], shares)
    rows = []
    for part_name, amount in zip(part_names, amounts[:3]):
        rows.append([part_name, "1", money(amount)])
    rows.append(["Body labor", f"{amounts[3] / 68:.1f} hrs", money(amounts[3])])
    rows.append(["Paint and materials", "", money(amounts[4])])
    rows.append(["TOTAL", "", money(claim["repair_estimate_amount"])])

    estimate_date = as_date(claim["loss_date"]) + datetime.timedelta(days=rng.randint(2, 12))
    fields = maybe_blank_fields([
        ("Estimate number", f"EST-{rng.randint(100000, 999999)}"),
        ("Estimate date", format_date(estimate_date, layout["date_format"])),
        ("Customer", person_name(facts)),
        ("Phone", facts["claimant"]["phone_number"]),
        ("Insurance claim", claim["claim_id"]),
        ("Vehicle", f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"),
        ("VIN", vehicle["vin"]),
        ("License plate", vehicle["license_plate"]),
    ], rng)
    page = title_block(shop["name"], "Repair Estimate",
                       [shop["street"], f"{shop['city']}, {shop['state']}", f"Phone {shop['phone_number']}"], layout)
    page.append(field_table(fields, layout))
    page.append(section_heading("Estimate details", layout))
    page.append(line_item_table(["Description", "Qty / Hours", "Amount"], rows, layout))
    file_path = folder / f"{claim['claim_id']}_repair_estimate.pdf"
    return document_row(facts, "repair_estimate", file_path, write_pdf(file_path, [page]))


def make_medical_records(facts, rng, folder):
    """Two pages: page 1 is the bill, page 2 is the treatment note."""
    claim, clinic = facts["claim"], facts["clinic"]
    layout = layout_for_id(clinic["provider_id"])
    visits = int(claim["treatment_visits"])
    first_visit = as_date(claim["loss_date"]) + datetime.timedelta(days=rng.randint(1, 6))
    last_visit = first_visit + datetime.timedelta(days=visits * rng.randint(3, 4))
    amounts = split_amount(claim["medical_bill_amount"],
                           [rng.uniform(0.08, 0.14), rng.uniform(0.35, 0.45), rng.uniform(0.25, 0.35), rng.uniform(0.1, 0.18)])
    rows = [
        ["99203 New patient evaluation", "1", money(amounts[0])],
        ["98941 Spinal manipulation", str(visits), money(amounts[1])],
        ["97110 Therapeutic exercise", str(visits), money(amounts[2])],
        ["97014 Electrical stimulation", str(max(1, visits // 2)), money(amounts[3])],
        ["TOTAL", "", money(claim["medical_bill_amount"])],
    ]
    header_lines = [clinic["street"], f"{clinic['city']}, {clinic['state']}", f"Phone {clinic['phone_number']}"]
    bill_fields = maybe_blank_fields([
        ("Patient", person_name(facts)),
        ("Date of birth", format_date(as_date(facts["claimant"]["date_of_birth"]), layout["date_format"])),
        ("Insurance claim", claim["claim_id"]),
        ("Date of injury", format_date(as_date(claim["loss_date"]), layout["date_format"])),
        ("First visit", format_date(first_visit, layout["date_format"])),
        ("Last visit", format_date(last_visit, layout["date_format"])),
        ("Number of visits", str(visits)),
    ], rng)
    bill_page = title_block(clinic["name"], "Itemized Medical Bill", header_lines, layout)
    bill_page.append(field_table(bill_fields, layout))
    bill_page.append(section_heading("Services", layout))
    bill_page.append(line_item_table(["Service", "Units", "Charge"], rows, layout))

    if facts["ring_id"] == "B":
        template = get_ring_template(RING_B_NOTE_PROMPT)
        note = add_typos(fill_placeholders(template, {"[VISITS]": str(visits)}), rng)
    else:
        note = write_free_text(
            f"Write a clinical treatment summary (about 150 words) by the treating provider for a patient "
            f"with {claim['injury_type']} after a {claim['accident_type']}. The patient had {visits} visits. "
            f"No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
            rng,
        )
    note_page = title_block(clinic["name"], "Treatment Summary", header_lines, layout)
    note_page.append(field_table([
        ("Patient", person_name(facts)),
        ("Treating provider", fake_person_name(f"clinician-{clinic['provider_id']}") + ", DC"),
        ("Diagnosis", claim["injury_type"]),
    ], layout))
    note_page.extend(text_block(note, layout))
    file_path = folder / f"{claim['claim_id']}_medical_records.pdf"
    return document_row(facts, "medical_records", file_path, write_pdf(file_path, [bill_page, note_page]))


def make_attorney_letter(facts, rng, folder):
    attorney, law_firm, claim = facts["attorney"], facts["law_firm"], facts["claim"]
    if attorney is None:
        return None
    layout = layout_for_id(law_firm["law_firm_id"])
    letter_date = as_date(claim["reported_date"]) + datetime.timedelta(days=rng.randint(3, 30))
    body = write_free_text(
        f"Write the body (about 120 words) of a letter of representation from a personal injury lawyer "
        f"to an auto insurer. The client was hurt in a {claim['accident_type']}. Ask that all contact go "
        f"through the law firm, ask for the policy limits, and ask the insurer to keep all evidence. "
        f"No salutation, no signature, no names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
        rng,
    )
    opening = (
        f"{format_date(letter_date, layout['date_format'])}\n\nClaims Department\n{INSURER_NAME}\n\n"
        f"Re: Claim {claim['claim_id']}\nOur client: {person_name(facts)}\n"
        f"Date of loss: {format_date(as_date(claim['loss_date']), layout['date_format'])}\n\nDear Claims Representative:"
    )
    closing = f"Sincerely,\n\n{attorney['name']}\n{law_firm['name']}"
    page = title_block(law_firm["name"], "Letter of Representation",
                       [f"{law_firm['city']}, {law_firm['state']}", f"Phone {law_firm['phone_number']}"], layout)
    page.extend(text_block(opening, layout) + text_block(body, layout) + text_block(closing, layout))
    file_path = folder / f"{claim['claim_id']}_attorney_letter.pdf"
    return document_row(facts, "attorney_letter", file_path, write_pdf(file_path, [page]))


def make_adjuster_file(facts, rng, folder):
    """Two pages: page 1 is the adjuster's claim notes, page 2 is the recorded statement."""
    claim = facts["claim"]
    layout = make_layout(0)
    layout["date_format"] = rng.choice(DATE_FORMATS)
    adjuster = fake_person_name(f"adjuster-{rng.randint(1, 6)}")
    represented = "is" if facts["attorney"] is not None else "is not"
    notes = write_free_text(
        f"Write 5 short claim log entries by an auto insurance adjuster for a {claim['accident_type']} "
        f"claim. Injury: {claim['injury_type']}. The claimant {represented} represented by a lawyer. Start "
        f"each entry on a new line with 'Entry 1:', 'Entry 2:' and so on. No names, dates or amounts. "
        f"(Internal reference {claim['claim_id']}; do not mention it.)",
        rng,
    )
    # Python puts the real dates on the entries, so the LLM never writes a date.
    entry_date = as_date(claim["reported_date"])
    for entry_number in range(1, 8):
        entry_date = entry_date + datetime.timedelta(days=rng.randint(1, 9))
        notes = notes.replace(f"Entry {entry_number}:", f"{format_date(entry_date, layout['date_format'])} -")
    notes = notes.replace("\n", "\n\n")

    statement = write_free_text(
        f"Write a recorded statement transcript (about 250 words) between an insurance adjuster (lines "
        f"start with 'Q:') and the claimant (lines start with 'A:'). The claimant was the {person_role(facts)} "
        f"in a {claim['accident_type']} in {claim['loss_city']}, Texas, and has {claim['injury_type']}. "
        f"No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
        rng, max_tokens=1800,
    )
    statement_date = as_date(claim["reported_date"]) + datetime.timedelta(days=rng.randint(2, 10))
    notes_page = title_block(INSURER_NAME, "Claim Notes", ["Bodily Injury Unit"], layout)
    notes_page.append(field_table([("Claim number", claim["claim_id"]), ("Claimant", person_name(facts)),
                                   ("Adjuster", adjuster)], layout))
    notes_page.extend(text_block(notes, layout))
    statement_page = title_block(INSURER_NAME, "Recorded Statement", ["Bodily Injury Unit"], layout)
    statement_page.append(field_table([
        ("Claim number", claim["claim_id"]), ("Statement of", person_name(facts)), ("Taken by", adjuster),
        ("Date", format_date(statement_date, layout["date_format"])),
    ], layout))
    statement_page.extend(text_block(statement.replace("\n", "\n\n"), layout))
    file_path = folder / f"{claim['claim_id']}_adjuster_file.pdf"
    return document_row(facts, "adjuster_file", file_path, write_pdf(file_path, [notes_page, statement_page]))
