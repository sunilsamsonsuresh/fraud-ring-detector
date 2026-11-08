"""Shared helpers for the claim PDFs, plus the FNOL and the attorney letter (PLAN.md A4, PLAN-v2.md V4).

Python fills every name, date, ID and amount from the tables. The LLM writes only free
text, from a fact sheet (fact_sheets.py) that never uses the rating labels. Plain code
checks every LLM text: no invented placeholders, no rating labels (one stricter retry).
Each builder returns one row for documents.csv, or None when the claim has no such document.

The other builders: incident_documents.py (police report, repair estimate),
care_documents.py (medical records, adjuster file), lawsuit_documents.py (court papers).
"""

import datetime
import re
import threading

from faker import Faker

from src import config
from src.datagen.fact_sheets import FORBIDDEN_LABELS, facts_for_document, find_forbidden_labels, replace_forbidden_labels
from src.datagen.noise import DATE_FORMATS, add_typos, format_date, maybe_blank_fields
from src.datagen.templates import (
    INSURER_NAME, field_table, layout_for_id, make_layout, section_heading, text_block, title_block, write_pdf,
)
from src.llm import ask_llm

SYSTEM_PROMPT = (
    "You write short, realistic text for SYNTHETIC (fake) auto insurance documents that are used "
    "to test software. Everything is fictional. Write plain text only: no markdown, no headings, "
    "no bullet symbols. Do not invent names of people or companies, dates, phone numbers or money "
    "amounts. Use a placeholder in square brackets only when the request asks for it. Express the "
    "facts you are given in your own words. Never use these words: " + ", ".join(FORBIDDEN_LABELS) + "."
)

# Shared story texts have no claim reference, so every claim of a story group gets the same
# cached text (copied stories, PLAN-v2.md A4). The placeholders are filled per claim.
RING_A_STORY_PROMPT = (
    "Write a first-person account (about 120 words) by a driver for an insurance claim form. "
    "The car in front stopped suddenly for no clear reason and the driver could not avoid a "
    "rear-end collision; the driver felt neck and back pain soon after. Use the exact placeholder "
    "[LOSS_DATE] for the date and [CITY] for the city. No names."
)
COPY_PAIR_STORY_PROMPT = (
    "Write a first-person account (about 120 words) by a driver for an insurance claim form. "
    "The driver was waiting to turn at an intersection when another car hit the side of the car; "
    "the driver felt shoulder pain that evening. Use the exact placeholder [LOSS_DATE] for the date "
    "and [CITY] for the city. No names. (Story group {group}; do not mention it.)"
)
INCIDENT_STORY_PROMPT = (
    "Write a first-person account (about 120 words) by a person in a car for an insurance claim form. "
    "Accident: {accident_type}. Several people were in the car and all were hurt. Use the exact "
    "placeholder [LOSS_DATE] for the date and [CITY] for the city. No names. (Story group {group}; do not mention it.)"
)

# Free text must not contain placeholders like [CLAIMANT NAME]: no code would fill them.
UNWANTED_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z_ ]+\]")

# Shared texts use a fixed max_tokens, so every caller makes the same cache key.
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


def ask_with_room(prompt, max_tokens):
    """Ask the LLM. A cut-off answer is not cached, so ask once more with twice the room.
    (Raising max_tokens for every call would change every cache key and pay again.)"""
    try:
        return ask_llm(prompt, config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, max_tokens)
    except RuntimeError as problem:
        if "cut off" not in str(problem):
            raise
        return ask_llm(prompt, config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, 2 * max_tokens)


def checked_text(prompt, max_tokens, is_template=False):
    """Ask the LLM. Retry once with a stricter prompt if the text has an invented placeholder
    or a rating label. A label that survives the retry is replaced with plain words.
    A shared template (is_template=True) keeps its placeholders on purpose, so only labels are checked."""
    text = ask_with_room(prompt, max_tokens)
    has_placeholder = UNWANTED_PLACEHOLDER.search(text) and not is_template
    if has_placeholder or find_forbidden_labels(text):
        stricter_prompt = prompt + " Never use the words: " + ", ".join(FORBIDDEN_LABELS) + "."
        if not is_template:
            stricter_prompt += " Never use square brackets or placeholders of any kind."
        text = ask_with_room(stricter_prompt, max_tokens)
        if UNWANTED_PLACEHOLDER.search(text) and not is_template:
            raise RuntimeError(f"The model still wrote a placeholder: {UNWANTED_PLACEHOLDER.search(text).group()}")
    return replace_forbidden_labels(text)


def get_ring_template(prompt):
    """Return a shared story text, with placeholders still in it."""
    return checked_text(prompt, RING_TEMPLATE_MAX_TOKENS, is_template=True)


def story_prompt_for(story_group, accident_type):
    """The shared prompt of a story group (ring_c copies court papers, see lawsuit_documents.py)."""
    if story_group == "ring_a":
        return RING_A_STORY_PROMPT
    if story_group.startswith("copy_pair_"):
        return COPY_PAIR_STORY_PROMPT.format(group=story_group)
    if story_group.startswith("incident_"):
        return INCIDENT_STORY_PROMPT.format(group=story_group, accident_type=accident_type)
    return None


def write_free_text(prompt, rng, max_tokens=1200):
    return add_typos(checked_text(prompt, max_tokens), rng)


def with_facts(prompt, document_type, facts):
    """Add the claim's fact sheet for this document type to a prompt."""
    fact_lines = facts_for_document(document_type, facts["profile"]["planted_features"])
    if not fact_lines:
        return prompt
    return (prompt + " Work these facts into the text naturally, in your own words, without "
            "listing them:\n" + fact_lines)


def as_date(iso_text):
    return datetime.date.fromisoformat(iso_text)


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

    story_prompt = story_prompt_for(facts["profile"]["story_group"] or "", claim["accident_type"])
    if story_prompt is not None:
        template = get_ring_template(story_prompt)
        story = fill_placeholders(template, {"[LOSS_DATE]": loss_date_text, "[CITY]": claim["loss_city"]})
        story = add_typos(story, rng)
    else:
        story = write_free_text(with_facts(
            f"Write a first-person account (about 120 words) by the {person_role(facts)} for an insurance "
            f"claim form. Accident: {claim['accident_type']} in {claim['loss_city']}, Texas. Injury: "
            f"{claim['injury_type']}. No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
            "fnol", facts), rng)

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


def make_attorney_letter(facts, rng, folder):
    attorney, law_firm, claim = facts["attorney"], facts["law_firm"], facts["claim"]
    if attorney is None:
        return None
    layout = layout_for_id(law_firm["law_firm_id"])
    letter_date = as_date(claim["reported_date"]) + datetime.timedelta(days=rng.randint(3, 30))
    if claim["attorney_retained_date"]:
        letter_date = as_date(claim["attorney_retained_date"]) + datetime.timedelta(days=rng.randint(1, 5))
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
