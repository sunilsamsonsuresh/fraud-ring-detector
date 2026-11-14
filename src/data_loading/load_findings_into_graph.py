"""Step 6 of loading the graph: Finding nodes, the rated facts from the PDFs.

The flow, for each PDF of a claim:
1. read_pdf_pages.py reads the pages.
2. extract_findings_from_pages.py: the LLM rates the features of each page. Plain code checks every
   rating and every quote.
3. This file saves the kept findings: one Finding node each, linked to the claim and to the Document.

A new reading replaces the old findings of the same document. A finding keeps its quote and its page
number, so a person can open the PDF and check it (CLAUDE.md, rules 5.6 and 5.17).

The Document nodes must exist (load_documents_into_graph.py).
"""

from neo4j import Driver

from src import config
from src.data_loading import pdf_loading_queries as queries
from src.data_loading.extract_findings_from_pages import (
    ask_for_findings,
    check_findings,
)
from src.data_loading.finding_features import features_for
from src.data_loading.read_pdf_pages import read_pdf_pages


def load_findings_of_document(driver, claim_id, document, pages, loss_date):
    """Rate, check and save the findings of one PDF. Return (kept findings, dropped findings, warnings)."""
    if not features_for(document["document_type"]):
        return (
            [],
            [],
            [],
        )  # no feature is read from this type of document (for example, a complaint)
    document_id = document["document_id"]
    kept, dropped, warnings = [], [], []
    for page in pages:
        answer = ask_for_findings(document["document_type"], page, len(pages))
        if answer is None:
            warnings.append(
                f"{document_id} page {page['page_number']}: no valid findings JSON (two tries). "
                "Page skipped."
            )
            continue
        page_kept, page_dropped = check_findings(
            answer, page, document["document_type"], document_id, loss_date
        )
        kept.extend(page_kept)
        dropped.extend(page_dropped)
    driver.execute_query(queries.DELETE_FINDINGS_OF_DOCUMENT, document_id=document_id)
    driver.execute_query(
        queries.SAVE_FINDINGS,
        claim_id=claim_id,
        document_id=document_id,
        document_type=document["document_type"],
        findings=kept,
    )
    return kept, dropped, warnings


def load_findings_of_claim(driver: Driver, claim_id, document_rows, loss_date):
    """Save the findings of all PDFs of one claim. Return (number kept, number dropped, warnings).

    An LLM failure (API down, bad key) raises RuntimeError and stops this claim."""
    kept_count, dropped_count, warnings = 0, 0, []
    for document in document_rows:
        try:
            pages = read_pdf_pages(config.PDFS_DIR / claim_id / document["file_name"])
        except (
            RuntimeError
        ) as problem:  # a missing or broken PDF: skip it, read the others
            warnings.append(str(problem))
            continue
        kept, dropped, document_warnings = load_findings_of_document(
            driver, claim_id, document, pages, loss_date
        )
        kept_count += len(kept)
        dropped_count += len(dropped)
        warnings.extend(document_warnings)
    return kept_count, dropped_count, warnings


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". Neo4j must be running. It rates the PDFs of ONE claim from the saved
# LLM answers and prints the findings. It writes nothing to the graph.
if __name__ == "__main__":
    from src.data_loading.load_documents_into_graph import (
        documents_of_claim,
        read_document_list,
    )
    from src.data_loading.load_entity_mentions_into_graph import read_claim_table_facts
    from src.graph.connection import open_neo4j_driver

    driver = open_neo4j_driver()
    try:
        loss_date = read_claim_table_facts(driver, "C-1088")["loss_date"]
    finally:
        driver.close()
    for document in documents_of_claim(read_document_list(), "C-1088"):
        if not features_for(document["document_type"]):
            continue
        pages = read_pdf_pages(config.PDFS_DIR / "C-1088" / document["file_name"])
        for page in pages:
            answer = ask_for_findings(document["document_type"], page, len(pages))
            kept, dropped = check_findings(
                answer,
                page,
                document["document_type"],
                document["document_id"],
                loss_date,
            )
            for finding in kept:
                print(
                    f"{finding['finding_id']:<50} {finding['value']!s:<26} {finding['confidence']}"
                )
