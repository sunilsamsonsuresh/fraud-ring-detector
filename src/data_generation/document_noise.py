"""Make documents imperfect, like real ones: typos, different
date formats and missing fields.

`rng` is a random.Random made for one claim, so the same claim always
gets the same noise.
"""

DATE_FORMATS = ["iso", "us_slash", "long", "day_month", "us_short"]

# Fields that a real form sometimes leaves empty. Names, dates and IDs stay.
FIELDS_THAT_CAN_BE_MISSING = [
    "Phone",
    "VIN",
    "License plate",
    "Policy number",
    "ZIP code",
    "Date of birth",
]
MISSING_FIELD_CHANCE = 0.08
TYPO_CHANCE_PER_WORD = 0.015


def format_date(date_value, date_format):
    """Write a date in one of several styles.

    Example for 5 March 2024: iso 2024-03-05, us_slash 03/05/2024,
    long March 5, 2024, day_month 5 Mar 2024, us_short 3-5-24.
    """
    if date_format == "iso":
        return date_value.isoformat()
    if date_format == "us_slash":
        return date_value.strftime("%m/%d/%Y")
    if date_format == "long":
        return f"{date_value.strftime('%B')} {date_value.day}, {date_value.year}"
    if date_format == "day_month":
        return f"{date_value.day} {date_value.strftime('%b')} {date_value.year}"
    if date_format == "us_short":
        return f"{date_value.month}-{date_value.day}-{date_value.strftime('%y')}"
    raise ValueError(f"Unknown date format: {date_format}")


def add_typos(text, rng):
    """Swap two neighbour letters in a few long words. Numbers are never changed."""
    words = text.split(" ")
    for position in range(len(words)):
        word = words[position]
        if len(word) >= 5 and word.isalpha() and rng.random() < TYPO_CHANCE_PER_WORD:
            letter_position = rng.randint(1, len(word) - 3)
            swapped = word[letter_position + 1] + word[letter_position]
            words[position] = (
                word[:letter_position] + swapped + word[letter_position + 2 :]
            )
    return " ".join(words)


def maybe_blank_fields(field_rows, rng):
    """Return a copy of (label, value) rows where some optional values are empty."""
    result = []
    for label, value in field_rows:
        if label in FIELDS_THAT_CAN_BE_MISSING and rng.random() < MISSING_FIELD_CHANCE:
            result.append((label, ""))
        else:
            result.append((label, value))
    return result


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.document_noise      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    import datetime
    import random

    day = datetime.date(2024, 3, 5)
    for date_format in DATE_FORMATS:
        print("1. format_date", date_format, "->", format_date(day, date_format))

    rng = random.Random("debug")
    text = " ".join(
        [
            "The insured vehicle was struck while waiting at the intersection near the hospital."
        ]
        * 20
    )
    changed = [
        (before, after)
        for before, after in zip(text.split(" "), add_typos(text, rng).split(" "))
        if before != after
    ]
    print(
        "2. add_typos changed",
        len(changed),
        "of",
        len(text.split(" ")),
        "words, for example:",
        changed[:3],
    )

    rows = [
        ("Phone", "713-555-0100"),
        ("VIN", "1HGCM82633A004352"),
        ("Claim number", "C-1001"),
    ]
    blank_phone_count = len(
        [
            seed
            for seed in range(1000)
            if maybe_blank_fields(rows, random.Random(seed))[0][1] == ""
        ]
    )
    print(
        "3. maybe_blank_fields: Phone was blank in",
        blank_phone_count,
        "of 1000 forms (the chance is 8%). Claim number is never blank.",
    )
