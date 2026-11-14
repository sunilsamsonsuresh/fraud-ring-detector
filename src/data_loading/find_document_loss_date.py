"""Find the loss date that ONE PDF states, and compare it with the loss date of the claims table.

The result goes on the Document node (pdf_loading_queries.SAVE_DOCUMENT_LOSS_DATE). Rule AS-7 in the
scoring reads it: "do the documents disagree on the loss date?" Plain code does this work. The LLM only
found the date text on the page (extract_entities_from_pages.py).
"""

from src.data_loading.parse_pdf_values import parse_date


def document_loss_date(table_loss_date, document_facts):
    """Return (loss date or None, page number or None, conflict True or False).

    document_facts: the checked facts of the pages of one document. If two pages state different dates,
    the first date that differs from the table wins, because the conflict is what matters."""
    found_date, found_page = None, None
    for fact in sorted(document_facts, key=lambda fact: fact["page_number"]):
        if fact["field"] != "loss_date":
            continue
        document_date = parse_date(fact["value_as_written"])
        if document_date is None:
            continue
        if found_date is None or (
            found_date == table_loss_date and document_date != table_loss_date
        ):
            found_date, found_page = document_date, fact["page_number"]
    return (
        found_date,
        found_page,
        found_date is not None and found_date != table_loss_date,
    )


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    import datetime

    table_date = datetime.date(2024, 5, 1)
    page_1 = {"field": "loss_date", "value_as_written": "May 1, 2024", "page_number": 1}
    page_2 = {"field": "loss_date", "value_as_written": "2024-05-04", "page_number": 2}
    print("Same date:   ", document_loss_date(table_date, [page_1]))
    print("Other date:  ", document_loss_date(table_date, [page_1, page_2]))
    print(
        "No loss date:",
        document_loss_date(
            table_date, [{"field": "phone", "value_as_written": "x", "page_number": 1}]
        ),
    )
