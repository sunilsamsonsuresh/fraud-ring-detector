"""Agent 1: Intake - from PDF pages to graph entities and findings (PLAN.md Step 6, PLAN-v2.md V6).

Input: state["claim_id"]. For each PDF page of the claim:
Entities (v1):
1. The cheap LLM lists the facts on the page as JSON (src/documents/extraction.py).
2. Plain code drops every value that is not really written on the page.
3. Plain code matches each entity to a graph node and saves a MENTIONS edge with the page number.
4. Plain code saves the loss date written in the document on its Document node (rule AS-7 reads it).
At the end, plain code compares the PDF values with the table values and lists the conflicts.
Findings (v2): the cheap LLM rates the features of the page; plain code checks each rating and
quote (src/documents/feature_extraction.py) and saves Finding nodes. A new reading replaces
the document's old findings.
"""

import csv

from src import config
from src.documents.conflicts import document_loss_date, find_conflicts
from src.documents.entity_matching import MATCHABLE_TYPES, load_match_lookups, match_entity
from src.documents.extraction import entities_and_facts, extract_page
from src.documents.feature_extraction import ask_for_findings, check_findings, features_for
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


def save_document(driver, document, pages):
    driver.execute_query(queries.SAVE_DOCUMENT, claim_id=document["claim_id"], document_id=document["document_id"],
                         document_type=document["document_type"], file_name=document["file_name"],
                         page_count=len(pages))


def read_one_document(driver, document, pages, claim_facts, lookups):
    """Extract, match and save one PDF. Return (entity results, page facts, warnings)."""
    document_id = document["document_id"]
    save_document(driver, document, pages)
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
    loss_date, page_number, has_conflict = document_loss_date(claim_facts["loss_date"], all_facts)
    driver.execute_query(queries.SAVE_DOCUMENT_LOSS_DATE, document_id=document_id, loss_date_in_pdf=loss_date,
                         page_number=page_number, loss_date_conflict=has_conflict)
    return all_results, all_facts, warnings


def read_document_findings(driver, claim_id, document, pages, loss_date):
    """Rate, check and save the findings of one PDF. Return (kept findings, dropped findings, warnings)."""
    document_id = document["document_id"]
    if not features_for(document["document_type"]):
        return [], [], []          # no feature is read from this document type (for example, a complaint)
    save_document(driver, document, pages)
    kept, dropped, warnings = [], [], []
    for page in pages:
        answer = ask_for_findings(document["document_type"], page, len(pages))
        if answer is None:
            warnings.append(f"{document_id} page {page['page_number']}: no valid findings JSON (two tries). Page skipped.")
            continue
        page_kept, page_dropped = check_findings(answer, page, document["document_type"], document_id, loss_date)
        kept.extend(page_kept)
        dropped.extend(page_dropped)
    driver.execute_query(queries.DELETE_FINDINGS_OF_DOCUMENT, document_id=document_id)
    driver.execute_query(queries.SAVE_FINDINGS, claim_id=claim_id, document_id=document_id,
                         document_type=document["document_type"], findings=kept)
    return kept, dropped, warnings


def intake(state):
    """The agent: read entities and findings of the claim."""
    return read_claim(state["claim_id"], read_entities=True, read_findings=True)


def read_claim(claim_id, read_entities, read_findings):
    documents = read_claim_documents(claim_id)
    if not documents:
        return {"error_message": f"No documents were found for claim {claim_id}."}

    driver = open_neo4j_driver()
    try:
        claim_facts = read_claim_facts(driver, claim_id)
        if claim_facts is None:
            return {"error_message": f"Claim {claim_id} was not found in the graph."}
        lookups = load_match_lookups(driver) if read_entities else None
        entity_results, page_facts, warnings, findings, dropped_findings = [], [], [], [], []
        for document in documents:
            try:
                pages = read_pdf_pages(config.PDFS_DIR / claim_id / document["file_name"])
            except RuntimeError as problem:   # a missing or broken PDF: skip it, read the others
                warnings.append(str(problem))
                continue
            # An LLM failure (API down, bad key) raises RuntimeError here and stops this claim.
            if read_entities:
                results, facts, document_warnings = read_one_document(driver, document, pages, claim_facts, lookups)
                entity_results.extend(results)
                page_facts.extend(facts)
                warnings.extend(document_warnings)
            if read_findings:
                kept, dropped, document_warnings = read_document_findings(driver, claim_id, document, pages,
                                                                          claim_facts["loss_date"])
                findings.extend(kept)
                dropped_findings.extend(dropped)
                warnings.extend(document_warnings)
    finally:
        driver.close()

    conflicts, conflict_warnings = find_conflicts(claim_facts, page_facts)
    return {
        "documents_read": len(documents),
        "entity_results": entity_results,
        "document_conflicts": conflicts,
        "findings": findings,
        "dropped_findings": dropped_findings,
        "intake_warnings": warnings + conflict_warnings,
    }
