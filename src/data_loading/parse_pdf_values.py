"""Turn values written in a PDF into values that plain code can compare.

PDFs write the same thing in many ways: "713-555-0142" or "(713) 555 0142", "2024-03-05" or "3-5-24".
The functions here make one standard form of each. Plain code does this work, and no LLM (CLAUDE.md, rule 5.1).
"""

import datetime
import json

# The 5 date styles of our PDFs, as strptime patterns. %m and %d also accept one digit,
# so "3-5-24" works with "%m-%d-%y".
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


def find_date_lines(page_text):
    """[(line number, date)] for every line that holds only a date. Example: the line "March 5, 2024"
    gives (line number, date(2024, 3, 5)). Adjuster notes have one such line above each entry."""
    found = []
    for line_number, line in enumerate(page_text.splitlines()):
        stripped = line.strip()
        if 6 <= len(stripped) <= 20:
            parsed = parse_date(stripped)
            if parsed is not None:
                found.append((line_number, parsed))
    return found


def appears_on_page(value, page_text):
    """True if the value is written on the page. Case and line breaks do not matter."""
    return " ".join(value.lower().split()) in " ".join(page_text.lower().split())


def parse_json_object(answer_text):
    """Return the JSON object in the text of an LLM answer as a dict, or None."""
    # The model sometimes wraps the JSON in ```json ... ```. Keep only the part between the braces.
    start, end = answer_text.find("{"), answer_text.rfind("}")
    try:
        answer = json.loads(answer_text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(answer, dict):
        return None
    return answer


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    print(
        normalize_phone("(713) 555 0142"),
        "|",
        normalize_code("pje 3330"),
        "|",
        normalize_text("Reyes,  DC."),
    )
    for text in [
        "2024-03-05",
        "3/5/2024",
        "March 5, 2024",
        "5 Mar 2024",
        "3-5-24",
        "not a date",
    ]:
        print(f"{text:<15} ->", parse_date(text))
    print(appears_on_page("rear-ended at a light", "He was   Rear-Ended\nat a light."))
    print(parse_json_object('Here: ```json {"findings": []} ```'))
