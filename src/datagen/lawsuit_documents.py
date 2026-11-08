"""Make the extra PDFs for a claim that went to a lawsuit (PLAN.md A4):
complaint (petition), demand letter, defense answer, deposition transcript
and settlement agreement.

As in claim_documents.py, Python fills names, dates and amounts. Money is
always a [DEMAND_AMOUNT] placeholder that Python fills from the tables.
Ring C claims in the story group "ring_c" share one complaint and one demand letter
text, so their documents have copied wording.
"""

import datetime

from src import config
from src.datagen.claim_documents import (
    SYSTEM_PROMPT, as_date, document_row, fake_person_name, fill_placeholders, get_ring_template,
    person_name, write_free_text,
)
from src.datagen.noise import add_typos, format_date
from src.datagen.templates import (
    DEFENSE_FIRM_NAME, INSURER_NAME, field_table, layout_for_id, make_layout, money, text_block, title_block, write_pdf,
)
from src.llm import ask_llm

COURT_LAYOUT_NUMBER = 7      # Times-Roman, centred titles
DEFENSE_LAYOUT_NUMBER = 9    # Courier

RING_C_COMPLAINT_PROMPT = (
    "Write the body (about 250 words) of a Texas personal injury petition by a car accident victim "
    "against an auto insurer, with the parts Parties, Facts, Negligence and Damages in plain text. "
    "Use the exact placeholders [PLAINTIFF_NAME] for the plaintiff, [LOSS_DATE] for the accident date, "
    "[CITY] for the city and [DEMAND_AMOUNT] for the money demanded. Say the plaintiff suffered serious "
    "and permanent injuries and will need future medical care. No other names or dates."
)
RING_C_DEMAND_PROMPT = (
    "Write the body (about 180 words) of a demand letter from a personal injury lawyer to an auto "
    "insurer before a lawsuit. Use the exact placeholders [CLIENT_NAME] for the client, [LOSS_DATE] "
    "for the accident date and [DEMAND_AMOUNT] for the money demanded. Say an expert review supports "
    "a permanent injury and give the insurer 30 days to pay. No other names or dates."
)


def cause_number(facts):
    lawsuit = facts["lawsuit"]
    return f"{lawsuit['filed_date'][:4]}-CV-{lawsuit['lawsuit_id'].split('-')[1]}"


def case_caption(facts):
    return [facts["court"]["name"], f"Cause No. {cause_number(facts)}",
            f"{person_name(facts)}, Plaintiff, v. {INSURER_NAME}, Defendant"]


def common_replacements(facts, date_format):
    return {
        "[PLAINTIFF_NAME]": person_name(facts), "[CLIENT_NAME]": person_name(facts),
        "[LOSS_DATE]": format_date(as_date(facts["claim"]["loss_date"]), date_format),
        "[CITY]": facts["claim"]["loss_city"],
        "[DEMAND_AMOUNT]": money(facts["lawsuit"]["demand_amount"]),
    }


def make_complaint(facts, rng, folder):
    claim, lawsuit = facts["claim"], facts["lawsuit"]
    layout = make_layout(COURT_LAYOUT_NUMBER)
    if facts["profile"]["story_group"] == "ring_c":     # copied wording (NL-4)
        body = get_ring_template(RING_C_COMPLAINT_PROMPT)
    else:
        body = ask_llm(
            f"Write the body (about 250 words) of a Texas personal injury petition by a car accident victim "
            f"against an auto insurer, with the parts Parties, Facts, Negligence and Damages in plain text. "
            f"Accident: {claim['accident_type']}. Injury: {claim['injury_type']}. Use the exact placeholders "
            f"[PLAINTIFF_NAME], [LOSS_DATE], [CITY] and [DEMAND_AMOUNT]. No other names or dates. "
            f"(Internal reference {claim['claim_id']}; do not mention it.)",
            config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, 1500,
        )
    body = add_typos(fill_placeholders(body, common_replacements(facts, layout["date_format"])), rng)
    page = title_block(facts["court"]["name"], "Plaintiff's Original Petition", case_caption(facts)[1:], layout)
    page.append(field_table([
        ("Filed", format_date(as_date(lawsuit["filed_date"]), layout["date_format"])),
        ("Plaintiff's counsel", f"{facts['attorney']['name']}, {facts['law_firm']['name']}"),
    ], layout))
    page.extend(text_block(body, layout))
    file_path = folder / f"{claim['claim_id']}_complaint.pdf"
    return document_row(facts, "complaint", file_path, write_pdf(file_path, [page]))


def make_demand_letter(facts, rng, folder):
    claim, lawsuit, law_firm, expert = facts["claim"], facts["lawsuit"], facts["law_firm"], facts["expert"]
    layout = layout_for_id(law_firm["law_firm_id"])
    if facts["profile"]["story_group"] == "ring_c":     # copied wording (NL-4)
        body = get_ring_template(RING_C_DEMAND_PROMPT)
    else:
        body = ask_llm(
            f"Write the body (about 180 words) of a demand letter from a personal injury lawyer to an auto "
            f"insurer before a lawsuit. Accident: {claim['accident_type']}. Injury: {claim['injury_type']}. "
            f"Use the exact placeholders [CLIENT_NAME], [LOSS_DATE] and [DEMAND_AMOUNT]. No other names or "
            f"dates. (Internal reference {claim['claim_id']}; do not mention it.)",
            config.CHEAP_MODEL_NAME, SYSTEM_PROMPT, 1200,
        )
    body = add_typos(fill_placeholders(body, common_replacements(facts, layout["date_format"])), rng)
    letter_date = as_date(lawsuit["filed_date"]) - datetime.timedelta(days=rng.randint(20, 60))
    opening = (f"{format_date(letter_date, layout['date_format'])}\n\nClaims Department\n{INSURER_NAME}\n\n"
               f"Re: Claim {claim['claim_id']} - Demand for settlement\n\nDear Claims Representative:")
    closing = (f"Expert review: {expert['name']}, {expert['specialty']}\n\n"
               f"Sincerely,\n\n{facts['attorney']['name']}\n{law_firm['name']}")
    page = title_block(law_firm["name"], "Settlement Demand",
                       [f"{law_firm['city']}, {law_firm['state']}", f"Phone {law_firm['phone_number']}"], layout)
    page.extend(text_block(opening, layout) + text_block(body, layout) + text_block(closing, layout))
    file_path = folder / f"{claim['claim_id']}_demand_letter.pdf"
    return document_row(facts, "demand_letter", file_path, write_pdf(file_path, [page]))


def make_defense_answer(facts, rng, folder):
    claim, lawsuit = facts["claim"], facts["lawsuit"]
    layout = make_layout(DEFENSE_LAYOUT_NUMBER)
    body = write_free_text(
        f"Write the body (about 150 words) of an insurer's answer to a personal injury petition in Texas: "
        f"a general denial and three affirmative defenses that fit a {claim['accident_type']}. Plain text. "
        f"Call the parties only 'Plaintiff' and 'Defendant'. No names, placeholders, dates or amounts. "
        f"(Internal reference {claim['claim_id']}; do not mention it.)",
        rng,
    )
    answer_date = as_date(lawsuit["filed_date"]) + datetime.timedelta(days=rng.randint(20, 45))
    defense_attorney = fake_person_name(f"defense-attorney-{rng.randint(1, 3)}")
    page = title_block(facts["court"]["name"], "Defendant's Original Answer", case_caption(facts)[1:], layout)
    page.append(field_table([
        ("Date", format_date(answer_date, layout["date_format"])),
        ("Counsel for defendant", f"{defense_attorney}, {DEFENSE_FIRM_NAME}"),
    ], layout))
    page.extend(text_block(body, layout))
    file_path = folder / f"{claim['claim_id']}_defense_answer.pdf"
    return document_row(facts, "defense_answer", file_path, write_pdf(file_path, [page]))


def make_deposition(facts, rng, folder):
    claim, lawsuit = facts["claim"], facts["lawsuit"]
    layout = make_layout(COURT_LAYOUT_NUMBER)
    transcript = write_free_text(
        f"Write part of a deposition transcript (about 400 words) of a plaintiff in a car accident lawsuit. "
        f"The defense lawyer asks (lines start with 'Q:') and the plaintiff answers (lines start with 'A:'). "
        f"Accident: {claim['accident_type']} in {claim['loss_city']}, Texas. Injury: {claim['injury_type']}. "
        f"Ask about the accident, treatment and daily life. No names, dates or amounts. "
        f"(Internal reference {claim['claim_id']}; do not mention it.)",
        rng, max_tokens=2500,
    )
    deposition_date = as_date(lawsuit["filed_date"]) + datetime.timedelta(days=rng.randint(60, 200))
    page = title_block(facts["court"]["name"], f"Oral Deposition of {person_name(facts)}", case_caption(facts)[1:], layout)
    page.append(field_table([
        ("Date", format_date(deposition_date, layout["date_format"])),
        ("Location", f"Offices of {facts['law_firm']['name']}"),
        ("Examining attorney", f"{fake_person_name(f'defense-attorney-{rng.randint(1, 3)}')}, {DEFENSE_FIRM_NAME}"),
        ("Defending attorney", f"{facts['attorney']['name']}, {facts['law_firm']['name']}"),
    ], layout))
    page.extend(text_block(transcript.replace("\n", "\n\n"), layout))
    file_path = folder / f"{claim['claim_id']}_deposition.pdf"
    return document_row(facts, "deposition", file_path, write_pdf(file_path, [page]))


def make_settlement_agreement(facts, rng, folder):
    """Template only. A release is standard wording, so no LLM call."""
    settlement = facts["settlement"]
    if settlement is None:
        return None
    claim = facts["claim"]
    layout = make_layout(DEFENSE_LAYOUT_NUMBER)
    settlement_date = format_date(as_date(settlement["settlement_date"]), layout["date_format"])
    text = (
        f"This Settlement Agreement and Release is made on {settlement_date} between {person_name(facts)} "
        f"(\"Plaintiff\") and {INSURER_NAME} (\"Insurer\").\n\n"
        f"1. Payment. Insurer will pay Plaintiff the total sum of {money(settlement['settlement_amount'])} "
        f"within 30 days.\n\n"
        f"2. Release. Plaintiff releases Insurer and its insureds from all claims arising from the accident "
        f"of {format_date(as_date(claim['loss_date']), layout['date_format'])} (Claim {claim['claim_id']}, "
        f"Cause No. {cause_number(facts)}).\n\n"
        f"3. Dismissal. The parties will file an agreed motion to dismiss the lawsuit with prejudice.\n\n"
        f"4. No admission. This agreement is not an admission of liability by any party.\n\n"
        f"Plaintiff: {person_name(facts)}\n\nPlaintiff's counsel: {facts['attorney']['name']}, "
        f"{facts['law_firm']['name']}\n\nFor the Insurer: {DEFENSE_FIRM_NAME}"
    )
    page = title_block(DEFENSE_FIRM_NAME, "Settlement Agreement and Release", case_caption(facts), layout)
    page.extend(text_block(text, layout))
    file_path = folder / f"{claim['claim_id']}_settlement_agreement.pdf"
    return document_row(facts, "settlement_agreement", file_path, write_pdf(file_path, [page]))
