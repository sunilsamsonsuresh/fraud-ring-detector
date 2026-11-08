"""Turn values written in a PDF into values that plain code can compare.

PDFs write the same thing in many ways: "713-555-0142" or "(713) 555 0142",
"2024-03-05" or "3-5-24". These functions make one standard form of each.
"""

import datetime

# The 5 date styles in our PDFs (see src/datagen/noise.py), as strptime patterns.
# %m and %d also accept one digit, so "3-5-24" works with "%m-%d-%y".
DATE_PATTERNS = ["%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%d %b %Y", "%m-%d-%y"]


def normalize_text(value):
    """Lower case, no commas or full stops, single spaces. "Reyes,  DC." -> "reyes dc"."""
    return " ".join(value.lower().replace(",", " ").replace(".", " ").split())


def normalize_phone(value):
    """Return "713-555-0142", or "" if the value is not a 10-digit US phone number."""
    digits = ""
    for character in value:
        if character.isdigit():
            digits += character
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def normalize_code(value):
    """For VINs, license plates and policy numbers: "pje 3330" -> "PJE3330"."""
    return value.upper().replace(" ", "").replace("-", "")


def parse_date(value):
    """Return a datetime.date, or None if the text is not a date in a known style."""
    text = " ".join(value.split())
    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
        # "%y" reads "55" as 2055. A date in the future must be from the 1900s (a birth date).
        if pattern.endswith("%y") and parsed > datetime.date.today():
            parsed = parsed.replace(year=parsed.year - 100)
        return parsed
    return None


def parse_amount(value):
    """Return a float, or None. "$5,994.80" -> 5994.8"""
    text = value.replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None
