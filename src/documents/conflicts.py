"""Compare values in the PDFs with the values in the tables (PLAN.md, Step 6).

A conflict is a value that both sides have, but that differs. Example: the
claims table says the loss date is 2024-05-01, the police report says 28 Apr 2024.
A value that is missing on one side is not a conflict.
"""

from src.documents.value_parsing import normalize_phone, parse_amount, parse_date

DATE_FIELDS = ["loss_date", "date_of_birth"]
AMOUNT_FIELDS = ["repair_estimate_total", "medical_bill_total"]
PHONE_FIELDS = ["phone"]
COMPARED_FIELDS = DATE_FIELDS + AMOUNT_FIELDS + PHONE_FIELDS
AMOUNT_TOLERANCE = 0.005   # half a cent: the same amount, written with or without ".00"


def read_document_value(field, value_as_written):
    """Return the value in a form we can compare, or None if it cannot be read."""
    if field in DATE_FIELDS:
        return parse_date(value_as_written)
    if field in AMOUNT_FIELDS:
        return parse_amount(value_as_written)
    phone = normalize_phone(value_as_written)
    return phone or None


def values_differ(field, table_value, document_value):
    if field in AMOUNT_FIELDS:
        return abs(table_value - document_value) > AMOUNT_TOLERANCE
    return table_value != document_value


def find_conflicts(claim_facts, page_facts):
    """claim_facts: {field: table value}. page_facts: [{"field", "value_as_written", "document_id", "page_number"}].

    Return (conflicts, warnings). A warning is a value that could not be read.
    """
    conflicts = []
    warnings = []
    for fact in page_facts:
        field = fact["field"]
        table_value = claim_facts.get(field)
        if table_value is None or table_value == "":
            continue   # the table has no value (for example, a passenger has no repair estimate)
        document_value = read_document_value(field, fact["value_as_written"])
        if document_value is None:
            warnings.append(f"{fact['document_id']} page {fact['page_number']}: cannot read "
                            f"{field} '{fact['value_as_written']}'.")
            continue
        if values_differ(field, table_value, document_value):
            conflicts.append({
                "document_id": fact["document_id"], "page_number": fact["page_number"], "field": field,
                "table_value": str(table_value), "document_value": fact["value_as_written"],
            })
    return conflicts, warnings
