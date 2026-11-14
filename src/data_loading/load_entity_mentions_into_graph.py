"""Step 5 of loading the graph: MENTIONS edges (which PDF mentions which node) and the loss date of each PDF.

The flow, for each PDF of a claim:
1. read_pdf_pages.py reads the pages.
2. extract_entities_from_pages.py: the LLM lists the entities and facts on each page. Plain code drops
   every value that is not on the page.
3. match_entities_to_graph_nodes.py: plain code finds the graph node of each entity.
4. This file saves one MENTIONS edge for each match, with the page number (CLAUDE.md, rule 6).
5. find_document_loss_date.py finds the loss date that the PDF states. This file saves it on the Document node.

The Document nodes must exist (load_documents_into_graph.py). A MENTIONS edge is medium trust: an LLM
read the page. An entity that matches no node, or many nodes, is skipped. We never guess.
"""

from neo4j import Driver

from src import config
from src.data_loading import pdf_loading_queries as queries
from src.data_loading.extract_entities_from_pages import (
    entities_and_facts,
    extract_page,
)
from src.data_loading.find_document_loss_date import document_loss_date
from src.data_loading.match_entities_to_graph_nodes import MATCHABLE_TYPES, match_entity
from src.data_loading.read_pdf_pages import read_pdf_pages


def read_claim_table_facts(driver, claim_id):
    """{"claimant_name", "loss_date"} from the tables, or None if the claim is not in the graph."""
    records, _, _ = driver.execute_query(
        queries.CLAIM_FACTS_FOR_PDF_READING, claim_id=claim_id
    )
    if not records:
        return None
    return {
        "claimant_name": records[0]["claimant_name"],
        "loss_date": records[0]["loss_date"].to_native(),
    }


def find_mentions_on_page(entities, page_number, lookups):
    """The MENTIONS edges to save for the entities of one page."""
    mentions = []
    for entity in entities:
        if entity["entity_type"] not in MATCHABLE_TYPES:
            continue  # for example a police officer: the graph has no such node
        target, method, _reason = match_entity(entity, lookups)
        if target is not None:
            mentions.append(
                {
                    "element_id": target["element_id"],
                    "page_number": page_number,
                    "value_as_written": entity["value"],
                    "match_method": method,
                }
            )
    return mentions


def load_mentions_of_document(driver, document, pages, table_facts, lookups):
    """Read, match and save one PDF. Return a list of warnings."""
    document_id = document["document_id"]
    all_mentions, all_facts, warnings = [], [], []
    for page in pages:
        answer = extract_page(document["document_type"], page, len(pages))
        if answer is None:
            warnings.append(
                f"{document_id} page {page['page_number']}: the LLM did not give valid JSON "
                "(two tries). Page skipped."
            )
            continue
        entities, facts, rejected_values = entities_and_facts(
            answer, page["text"], table_facts["claimant_name"]
        )
        for rejected_value in rejected_values:
            warnings.append(
                f"{document_id} page {page['page_number']}: ignored {rejected_value}."
            )
        for fact in facts:
            fact["page_number"] = page["page_number"]
        all_facts.extend(facts)
        all_mentions.extend(
            find_mentions_on_page(entities, page["page_number"], lookups)
        )

    driver.execute_query(
        queries.SAVE_MENTIONS, document_id=document_id, mentions=all_mentions
    )
    loss_date, page_number, has_conflict = document_loss_date(
        table_facts["loss_date"], all_facts
    )
    driver.execute_query(
        queries.SAVE_DOCUMENT_LOSS_DATE,
        document_id=document_id,
        loss_date_in_pdf=loss_date,
        page_number=page_number,
        loss_date_conflict=has_conflict,
    )
    return warnings


def load_entity_mentions_of_claim(driver: Driver, claim_id, document_rows, lookups):
    """Save the mentions and the loss dates of all PDFs of one claim. Return a list of warnings.

    An LLM failure (API down, bad key) raises RuntimeError and stops this claim."""
    table_facts = read_claim_table_facts(driver, claim_id)
    if table_facts is None:
        return [f"Claim {claim_id} was not found in the graph."]
    warnings = []
    for document in document_rows:
        try:
            pages = read_pdf_pages(config.PDFS_DIR / claim_id / document["file_name"])
        except (
            RuntimeError
        ) as problem:  # a missing or broken PDF: skip it, read the others
            warnings.append(str(problem))
            continue
        warnings.extend(
            load_mentions_of_document(driver, document, pages, table_facts, lookups)
        )
    return warnings


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". Neo4j must be running. It READS the graph and the saved LLM answers
# for ONE PDF and shows what would be saved. It writes nothing. A page that is not in the cache
# would need the API key: the snippet then stops with a clear message.
if __name__ == "__main__":
    from src.data_loading.load_documents_into_graph import (
        documents_of_claim,
        read_document_list,
    )
    from src.data_loading.match_entities_to_graph_nodes import load_match_lookups
    from src.graph.connection import open_neo4j_driver

    driver = open_neo4j_driver()
    try:
        table_facts = read_claim_table_facts(driver, "C-1088")
        lookups = load_match_lookups(driver)
        document = documents_of_claim(read_document_list(), "C-1088")[0]
        pages = read_pdf_pages(config.PDFS_DIR / "C-1088" / document["file_name"])
        answer = extract_page(document["document_type"], pages[0], len(pages))
        entities, facts, rejected = entities_and_facts(
            answer, pages[0]["text"], table_facts["claimant_name"]
        )
        print(
            "Document:",
            document["document_id"],
            "| table loss date:",
            table_facts["loss_date"],
        )
        print(
            "Mentions that would be saved:", find_mentions_on_page(entities, 1, lookups)
        )
        print(
            "Loss date in the PDF:",
            document_loss_date(
                table_facts["loss_date"], [dict(fact, page_number=1) for fact in facts]
            ),
        )
    finally:
        driver.close()
