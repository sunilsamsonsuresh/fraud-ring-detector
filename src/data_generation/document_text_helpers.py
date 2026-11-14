"""Shared helpers of the PDF builders: the LLM text rules, names, dates and the documents.csv row.

Python fills every name, date, ID and amount from the tables. The LLM writes only free text, from a
fact sheet (fact_sheets.py) that never uses the rating labels. Plain code checks every LLM text:
no invented placeholders, no rating labels (one stricter retry).
"""

import datetime
import re

from faker import Faker

from src import config
from src.data_generation.document_noise import add_typos
from src.data_generation.fact_sheets import (
    FORBIDDEN_LABELS,
    facts_for_document,
    find_forbidden_labels,
    replace_forbidden_labels,
)
from src.llm import ask_llm

SYSTEM_PROMPT = (
    "You write short, realistic text for SYNTHETIC (fake) auto insurance documents that are used "
    "to test software. Everything is fictional. Write plain text only: no markdown, no headings, "
    "no bullet symbols. Do not invent names of people or companies, dates, phone numbers or money "
    "amounts. Use a placeholder in square brackets only when the request asks for it. Express the "
    "facts you are given in your own words. Never use these words: "
    + ", ".join(FORBIDDEN_LABELS)
    + "."
)

# Shared story texts have no claim reference, so every claim of a story group gets the same
# cached text (copied stories). The placeholders are filled per claim.
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


def fake_person_name(key):
    """The same key always gives the same name (for example, one doctor per clinic)."""
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
        stricter_prompt = (
            prompt + " Never use the words: " + ", ".join(FORBIDDEN_LABELS) + "."
        )
        if not is_template:
            stricter_prompt += " Never use square brackets or placeholders of any kind."
        text = ask_with_room(stricter_prompt, max_tokens)
        if UNWANTED_PLACEHOLDER.search(text) and not is_template:
            raise RuntimeError(
                f"The model still wrote a placeholder: {UNWANTED_PLACEHOLDER.search(text).group()}"
            )
    return replace_forbidden_labels(text)


def get_ring_template(prompt):
    """Return a shared story text, with placeholders still in it."""
    return checked_text(prompt, RING_TEMPLATE_MAX_TOKENS, is_template=True)


def story_prompt_for(story_group, accident_type):
    """The shared prompt of a story group (ring_c copies court papers, see make_lawsuit_documents.py)."""
    if story_group == "ring_a":
        return RING_A_STORY_PROMPT
    if story_group.startswith("copy_pair_"):
        return COPY_PAIR_STORY_PROMPT.format(group=story_group)
    if story_group.startswith("incident_"):
        return INCIDENT_STORY_PROMPT.format(
            group=story_group, accident_type=accident_type
        )
    return None


def write_free_text(prompt, rng, max_tokens=1200):
    return add_typos(checked_text(prompt, max_tokens), rng)


def with_facts(prompt, document_type, facts):
    """Add the claim's fact sheet for this document type to a prompt."""
    fact_lines = facts_for_document(document_type, facts["profile"]["planted_features"])
    if not fact_lines:
        return prompt
    return (
        prompt
        + " Work these facts into the text naturally, in your own words, without "
        "listing them:\n" + fact_lines
    )


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
    return {
        "document_id": f"{claim_id}-{document_type}",
        "claim_id": claim_id,
        "document_type": document_type,
        "file_name": file_path.name,
        "page_count": page_count,
    }


def person_name(facts):
    return f"{facts['claimant']['first_name']} {facts['claimant']['last_name']}"


def person_role(facts):
    return "passenger" if facts["claim"]["repair_shop_id"] == "" else "driver"


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.document_text_helpers      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    print(
        "1. split_amount(100.00, [1, 1, 1]):",
        split_amount(100.00, [1, 1, 1]),
        "(adds up to the exact cent)",
    )
    print(
        "2. fake_person_name twice:",
        fake_person_name("clinician-PR-0001"),
        "|",
        fake_person_name("clinician-PR-0001"),
    )
    print(
        "3. fill_placeholders:",
        fill_placeholders(
            "On [LOSS_DATE] in [CITY].", {"[LOSS_DATE]": "5 Mar 2024", "[CITY]": "Katy"}
        ),
    )
    print(
        "4. story_prompt_for('copy_pair_3', ...) starts with:",
        story_prompt_for("copy_pair_3", "x")[:50],
    )
    print(
        "5. UNWANTED_PLACEHOLDER finds:",
        UNWANTED_PLACEHOLDER.search("Dear [CLAIMANT NAME], hello").group(),
    )
