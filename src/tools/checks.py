"""The gate in front of the tools: plain code checks a claim ID before any tool runs.

A value from an agent (an LLM) is not trusted. It may have spaces, small letters, a wrong
format, or even query text. The gate cleans it or refuses it (CLAUDE.md, rule 10).
A refused value gives a message. It never runs a query, and we never guess what was meant.
"""

import re

CLAIM_ID_PATTERN = re.compile(r"C-[0-9]{4}")  # a claim ID looks like C-1026
COMMUNITY_ID_PATTERN = re.compile(r"COM-[0-9]{2,3}")  # a community ID looks like COM-01
MAX_SHOWN_CHARACTERS = 30  # a long bad value must not fill the message
MIN_NAME_CHARACTERS = 3  # "Law" is the shortest useful name search
BAND_FILTERS = [
    "any",
    "very high",
    "high",
    "medium",
    "low",
]  # what list_claims_by_score can filter by
GROUP_KINDS = [
    "phone",
    "address",
    "clinic_and_attorney",
    "firm_and_expert",
]  # what find_shared_groups can list
MAX_TEXT_CHARACTERS = 200  # a name or a topic longer than this is cut


def check_claim_id(text):
    """Return (claim_id, None) when the text is a claim ID, else (None, a message for the caller).

    It removes spaces at the ends and changes small letters to capital letters: " c-1026 " -> "C-1026"."""
    if not isinstance(text, str):
        return None, "The claim ID must be text. A claim ID looks like C-1026."
    claim_id = text.strip().upper()
    # fullmatch: the WHOLE text must be a claim ID. [0-9]: only the digits 0 to 9, not digits of other alphabets.
    if not CLAIM_ID_PATTERN.fullmatch(claim_id):
        shown = text.strip()[:MAX_SHOWN_CHARACTERS]
        return None, f"'{shown}' is not a claim ID. A claim ID looks like C-1026."
    return claim_id, None


def run_for_claim(driver, claim_text, tool_function):
    """Check the claim ID, then run one tool for it: tool_function(driver, claim_id).

    Every tool that takes a claim ID is called through this function."""
    claim_id, problem = check_claim_id(claim_text)
    if problem is not None:
        return {"message": problem}
    return tool_function(driver, claim_id)


def check_phone(text):
    """Return (phone, None) with the phone as stored ("713-555-0142") or its last 7 digits ("555-0142").
    Else return (None, a message). Any other text is refused: it is never used in a query."""
    if not isinstance(text, str):
        return (
            None,
            "The phone number must be text. Give 7 or 10 digits, for example 713-555-0142.",
        )
    digits = "".join(character for character in text if character in "0123456789")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}", None
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}", None
    shown = text.strip()[:MAX_SHOWN_CHARACTERS]
    return (
        None,
        f"'{shown}' is not a phone number. Give 7 or 10 digits, for example 713-555-0142.",
    )


def check_name(text):
    """Return (name, None) for the name of a clinic, repair shop, attorney or law firm, else (None, a message).

    A name that is too short would match almost everything, so it is refused."""
    if not isinstance(text, str):
        return None, "The name must be text."
    name = text.strip()[:MAX_TEXT_CHARACTERS]
    if len(name) < MIN_NAME_CHARACTERS:
        return (
            None,
            f"The name '{name}' is too short. Give at least {MIN_NAME_CHARACTERS} letters.",
        )
    return name, None


def check_topic(text):
    """Return (topic, None) for a search topic (a few words), else (None, a message)."""
    if not isinstance(text, str) or not text.strip():
        return (
            None,
            "The topic is empty. Give a few words, for example 'passenger not in the car'.",
        )
    return text.strip()[:MAX_TEXT_CHARACTERS], None


def check_group_kind(text):
    """Return (kind, None) when the text is one of GROUP_KINDS, else (None, a message that lists the allowed kinds)."""
    kind = text.strip().lower() if isinstance(text, str) else ""
    if kind not in GROUP_KINDS:
        return None, f"The kind of group must be one of: {', '.join(GROUP_KINDS)}."
    return kind, None


def check_band(text):
    """Return (band, None) with the band as the scoring engine writes it ("Very High", "High", ...) or "any".
    Else return (None, a message that lists the allowed bands)."""
    band = text.strip().lower().replace("_", " ") if isinstance(text, str) else ""
    if band not in BAND_FILTERS:
        return None, f"The band must be one of: {', '.join(BAND_FILTERS)}."
    return ("any" if band == "any" else band.title()), None


def check_community_or_claim(text):
    """Return (("community", "COM-01"), None) or (("claim", "C-1026"), None), else (None, a message).

    It removes spaces at the ends and changes small letters to capital letters: " com-01 " -> "COM-01"."""
    value = text.strip().upper() if isinstance(text, str) else ""
    if COMMUNITY_ID_PATTERN.fullmatch(value):
        return ("community", value), None
    if CLAIM_ID_PATTERN.fullmatch(value):
        return ("claim", value), None
    shown = str(text).strip()[:MAX_SHOWN_CHARACTERS]
    return None, (
        f"'{shown}' is not a community ID or a claim ID. They look like COM-01 and C-1026."
    )
