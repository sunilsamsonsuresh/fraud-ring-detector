"""Agent 1: Intake - from PDF pages to graph entities (PLAN.md, Step 6).

Input: state["claim_id"]. For each PDF page of the claim:
1. Plain code reads the page text.
2. The cheap LLM lists the facts on the page as JSON (src/documents/extraction.py).
3. Plain code drops every value that is not really written on the page.
4. Plain code matches each entity to a graph node and saves a MENTIONS edge with the page number.
At the end, plain code compares the PDF values with the table values and lists the conflicts.
"""

import csv

from src import config
from src.documents.conflicts import find_conflicts
from src.documents.entity_matching import MATCHABLE_TYPES, load_match_lookups, match_entity
from src.documents.extraction import entities_and_facts, extract_page
from src.documents.pdf_reader import read_pdf_pages
from src.graph import queries
from src.graph.connection import open_neo4j_driver


def read_claim_documents(claim_id):
    """The rows of data/pdfs/documents.csv for one claim."""
    documents_file = config.PDFS_DIR / "documents.csv"
    if not documents_file.exists():
        raise RuntimeError(f"{documents_file} is missing. Run: python main.py generate-data --pdfs")
    documents = []
    with open(documents_file, newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            if row["claim_id"] == claim_id:
                documents.append(row)
    return documents


def read_claim_facts(driver, claim_id):
    """The table values that we compare with the PDFs. None if the claim is not in the graph."""
    records, _, _ = driver.execute_query(queries.CLAIM_FACTS_FOR_CONFLICTS, claim_id=claim_id)
    if not records:
        return None
    facts = dict(records[0])
    for field in ["loss_date", "date_of_birth"]:
        facts[field] = facts[field].to_native()   # Neo4j date -> Python date
    return facts


def match_page_entities(entities, document, page_number, lookups):
    """Return (one result per entity, the MENTIONS edges to save)."""
    results = []
    mentions = []
    for entity in entities:
        result = {"document_id": document["document_id"], "page_number": page_number,
                  "entity_type": entity["entity_type"], "value_as_written": entity["value"]}
        if entity["entity_type"] not in MATCHABLE_TYPES:
            result["status"] = "not_in_graph"     # for example, a police officer: the graph has no such node
        else:
            target, method, reason = match_entity(entity, lookups)
            if target is None:
                result.update({"status": "unmatched", "reason": reason})
            else:
                result.update({"status": "matched", "match_method": method,
                               "node_label": target["label"], "node_id": target["node_id"]})
                mentions.append({"element_id": target["element_id"], "page_number": page_number,
                                 "value_as_written": entity["value"], "match_method": method})
        results.append(result)
    return results, mentions


def read_one_document(driver, document, pages, claim_facts, lookups):
    """Extract, match and save one PDF. Return (entity results, page facts, warnings)."""
    document_id = document["document_id"]
    driver.execute_query(queries.SAVE_DOCUMENT, claim_id=document["claim_id"], document_id=document_id,
                         document_type=document["document_type"], file_name=document["file_name"],
                         page_count=len(pages))
    all_results, all_facts, warnings, all_mentions = [], [], [], []
    for page in pages:
        answer = extract_page(document["document_type"], page, len(pages))
        if answer is None:
            warnings.append(f"{document_id} page {page['page_number']}: the LLM did not give valid JSON "
                            "(two tries). Page skipped.")
            continue
        entities, facts, rejected_values = entities_and_facts(answer, page["text"], claim_facts["claimant_name"])
        for rejected_value in rejected_values:
            warnings.append(f"{document_id} page {page['page_number']}: ignored {rejected_value}.")
        for fact in facts:
            fact["document_id"] = document_id
            fact["page_number"] = page["page_number"]
        results, mentions = match_page_entities(entities, document, page["page_number"], lookups)
        all_results.extend(results)
        all_facts.extend(facts)
        all_mentions.extend(mentions)
    driver.execute_query(queries.SAVE_MENTIONS, document_id=document_id, mentions=all_mentions)
    return all_results, all_facts, warnings


def intake(state):
    claim_id = state["claim_id"]
    documents = read_claim_documents(claim_id)
    if not documents:
        return {"error_message": f"No documents were found for claim {claim_id}."}

    driver = open_neo4j_driver()
    try:
        claim_facts = read_claim_facts(driver, claim_id)
        if claim_facts is None:
            return {"error_message": f"Claim {claim_id} was not found in the graph."}
        lookups = load_match_lookups(driver)
        entity_results, page_facts, warnings = [], [], []
        for document in documents:
            try:
                pages = read_pdf_pages(config.PDFS_DIR / claim_id / document["file_name"])
            except RuntimeError as problem:   # a missing or broken PDF: skip it, read the others
                warnings.append(str(problem))
                continue
            # An LLM failure (API down, bad key) raises RuntimeError here and stops this claim.
            results, facts, document_warnings = read_one_document(driver, document, pages, claim_facts, lookups)
            entity_results.extend(results)
            page_facts.extend(facts)
            warnings.extend(document_warnings)
    finally:
        driver.close()

    conflicts, conflict_warnings = find_conflicts(claim_facts, page_facts)
    return {
        "documents_read": len(documents),
        "entity_results": entity_results,
        "document_conflicts": conflicts,
        "intake_warnings": warnings + conflict_warnings,
    }
