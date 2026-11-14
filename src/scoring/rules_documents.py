"""The yes/no check of the rule that reads PDF evidence: AS-7.

AS means "accident story". AS-7: do the documents of the claim give a different loss date
than the claims table? The loss dates in the PDFs were read when the PDFs were loaded into the graph.
Plain code compares the dates here. The LLM decides nothing (CLAUDE.md, rule 16).

Every conflict in the proof names the document and the page number, so a human can open the PDF
and check (CLAUDE.md, rule 6).
"""

from src.scoring.rule_results import fired_or_not, not_evaluated


def check_as_7(facts):
    """Documents disagree on the loss date: a PDF states a loss date that is not the date in the table."""
    documents_with_a_date = []
    for document in facts["document_loss_dates"]:
        if document["loss_date_in_pdf"] is not None:
            documents_with_a_date.append(document)
    if not documents_with_a_date:
        return not_evaluated("no document states a loss date")

    conflicts = []
    for document in documents_with_a_date:
        if document["loss_date_in_pdf"] != facts["loss_date"]:
            conflicts.append(
                f"{document['document_id']} page {document['page_number']}: "
                f"{document['loss_date_in_pdf']}"
            )
    return fired_or_not(
        len(conflicts) > 0,
        {
            "table_loss_date": facts["loss_date"],
            "documents_checked": len(documents_with_a_date),
            "conflicts": conflicts,
        },
    )


DOCUMENT_RULE_CHECKS = {"AS-7": check_as_7}


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    import datetime

    table_loss_date = datetime.date(2025, 3, 1)
    sample_facts = {
        "loss_date": table_loss_date,
        "document_loss_dates": [
            {
                "document_id": "C-0000-fnol",
                "document_type": "fnol",
                "loss_date_in_pdf": table_loss_date,
                "page_number": 1,
            },
            {
                "document_id": "C-0000-police_report",
                "document_type": "police_report",
                "loss_date_in_pdf": datetime.date(2025, 3, 5),
                "page_number": 2,
            },  # a different date: conflict
            {
                "document_id": "C-0000-adjuster_file",
                "document_type": "adjuster_file",
                "loss_date_in_pdf": None,
                "page_number": None,
            },  # states no date: skipped
        ],
    }
    print("AS-7", check_as_7(sample_facts))
