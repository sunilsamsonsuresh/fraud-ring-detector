"""Two PDFs of every claim that has them: the first notice of loss (FNOL) and the attorney letter.

FNOL: a form of fields, and the claimant's own account of the accident. Claims of one story group
get the same shared account text (copied stories). The attorney letter exists only when the claim has
an attorney. Each builder returns one row for documents.csv, or None when the claim has no such document.
"""

import datetime

from src.data_generation.document_noise import (
    DATE_FORMATS,
    add_typos,
    format_date,
    maybe_blank_fields,
)
from src.data_generation.document_text_helpers import (
    as_date,
    document_row,
    fill_placeholders,
    get_ring_template,
    person_name,
    person_role,
    story_prompt_for,
    with_facts,
    write_free_text,
)
from src.data_generation.pdf_layout import (
    INSURER_NAME,
    field_table,
    layout_for_id,
    make_layout,
    section_heading,
    text_block,
    title_block,
    write_pdf,
)


def make_fnol(facts, rng, folder):
    claim, claimant, address, vehicle = (
        facts["claim"],
        facts["claimant"],
        facts["address"],
        facts["vehicle"],
    )
    layout = make_layout(0)
    layout["date_format"] = rng.choice(DATE_FORMATS)
    loss_date_text = format_date(as_date(claim["loss_date"]), layout["date_format"])

    story_prompt = story_prompt_for(
        facts["profile"]["story_group"] or "", claim["accident_type"]
    )
    if story_prompt is not None:
        template = get_ring_template(story_prompt)
        story = fill_placeholders(
            template, {"[LOSS_DATE]": loss_date_text, "[CITY]": claim["loss_city"]}
        )
        story = add_typos(story, rng)
    else:
        story = write_free_text(
            with_facts(
                f"Write a first-person account (about 120 words) by the {person_role(facts)} for an insurance "
                f"claim form. Accident: {claim['accident_type']} in {claim['loss_city']}, Texas. Injury: "
                f"{claim['injury_type']}. No names, no dates. (Internal reference {claim['claim_id']}; do not mention it.)",
                "fnol",
                facts,
            ),
            rng,
        )

    fields = maybe_blank_fields(
        [
            ("Claim number", claim["claim_id"]),
            (
                "Date reported",
                format_date(as_date(claim["reported_date"]), layout["date_format"]),
            ),
            ("Date of loss", loss_date_text),
            ("Loss location", f"{claim['loss_city']}, TX"),
            ("Type of accident", claim["accident_type"]),
            ("Claimant name", person_name(facts)),
            ("Claimant role", person_role(facts)),
            (
                "Date of birth",
                format_date(as_date(claimant["date_of_birth"]), layout["date_format"]),
            ),
            ("Street address", address["street"]),
            ("City / State", f"{address['city']}, {address['state']}"),
            ("ZIP code", address["zip_code"]),
            ("Phone", claimant["phone_number"]),
            ("Policy number", claim["policy_id"]),
            ("Vehicle", f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"),
            ("VIN", vehicle["vin"]),
            ("License plate", vehicle["license_plate"]),
            ("Reported injury", claim["injury_type"]),
        ],
        rng,
    )
    page = title_block(
        INSURER_NAME,
        "First Notice of Loss (FNOL)",
        ["Claims Department - Houston Service Center"],
        layout,
    )
    page.append(field_table(fields, layout))
    page.append(
        section_heading("Description of the accident (claimant's words)", layout)
    )
    page.extend(text_block(story, layout))
    file_path = folder / f"{claim['claim_id']}_fnol.pdf"
    return document_row(facts, "fnol", file_path, write_pdf(file_path, [page]))


def make_attorney_letter(facts, rng, folder):
    attorney, law_firm, claim = facts["attorney"], facts["law_firm"], facts["claim"]
    if attorney is None:
        return None
    layout = layout_for_id(law_firm["law_firm_id"])
    letter_date = as_date(claim["reported_date"]) + datetime.timedelta(
        days=rng.randint(3, 30)
    )
    if claim["attorney_retained_date"]:
        letter_date = as_date(claim["attorney_retained_date"]) + datetime.timedelta(
            days=rng.randint(1, 5)
        )
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
    page = title_block(
        law_firm["name"],
        "Letter of Representation",
        [
            f"{law_firm['city']}, {law_firm['state']}",
            f"Phone {law_firm['phone_number']}",
        ],
        layout,
    )
    page.extend(
        text_block(opening, layout)
        + text_block(body, layout)
        + text_block(closing, layout)
    )
    file_path = folder / f"{claim['claim_id']}_attorney_letter.pdf"
    return document_row(
        facts, "attorney_letter", file_path, write_pdf(file_path, [page])
    )


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.make_fnol_and_attorney_letter      (needs no Neo4j; the LLM texts come from the saved answers in data/cache/)
if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    from src.data_generation.generate_pdfs import facts_for_one_claim

    facts, rng = facts_for_one_claim("C-1001")
    folder = Path(tempfile.mkdtemp())
    print("1. make_fnol:", make_fnol(facts, rng, folder))
    print(
        "2. make_attorney_letter:",
        make_attorney_letter(facts, rng, folder),
        "(None = this claim has no attorney)",
    )
    print("PDFs are in", folder)
