"""Run all the PDF steps for a list of claims, in the right order.

The order matters, because each step needs the nodes of the step before:
  tables (Claim nodes)  ->  1. documents  ->  2. chunks  ->  3. entity mentions  ->  4. findings
Step 0, the tables, is load_tables_into_graph.py. Run it first.

Cost: steps 3 and 4 call the LLM once for each PDF page. Every answer is saved in data/cache/, so a page that
was read before costs nothing. A page that is new costs money and needs ANTHROPIC_API_KEY. Test with a few
claims first (CLAUDE.md, section 7).

Run it for some claims:  .venv/bin/python -m src.data_loading.load_pdfs_into_graph C-1088 C-1089
Run it for all claims:   .venv/bin/python -m src.data_loading.load_pdfs_into_graph --all
"""

import sys

from neo4j import Driver

from src.data_loading.load_chunks_into_graph import load_chunks_into_graph
from src.data_loading.load_documents_into_graph import (
    documents_of_claim,
    load_documents_into_graph,
    read_document_list,
)
from src.data_loading.load_entity_mentions_into_graph import (
    load_entity_mentions_of_claim,
    read_claim_table_facts,
)
from src.data_loading.load_findings_into_graph import load_findings_of_claim
from src.data_loading.match_entities_to_graph_nodes import load_match_lookups


def load_pdfs_into_graph(driver: Driver, claim_ids=None):
    """Load the PDFs of these claims (all claims if claim_ids is None). Return {"claims", "chunks", "findings", "warnings"}."""
    document_rows = read_document_list()
    all_claim_ids = []
    for row in document_rows:
        if row["claim_id"] not in all_claim_ids:
            all_claim_ids.append(row["claim_id"])
    if claim_ids is None:
        claim_ids = all_claim_ids
    for claim_id in claim_ids:
        if claim_id not in all_claim_ids:
            raise ValueError(f"Claim {claim_id} has no documents in documents.csv.")

    lookups = load_match_lookups(
        driver
    )  # read one time: the graph nodes that entities can match
    chunk_count, finding_count, warnings = 0, 0, []
    for number, claim_id in enumerate(claim_ids, start=1):
        rows = documents_of_claim(document_rows, claim_id)
        load_documents_into_graph(driver, rows)
        claim_chunks, chunk_warnings = load_chunks_into_graph(driver, rows)
        warnings.extend(chunk_warnings)
        warnings.extend(load_entity_mentions_of_claim(driver, claim_id, rows, lookups))
        table_facts = read_claim_table_facts(driver, claim_id)
        kept, _dropped, finding_warnings = load_findings_of_claim(
            driver, claim_id, rows, table_facts["loss_date"]
        )
        warnings.extend(finding_warnings)
        chunk_count += claim_chunks
        finding_count += kept
        if number % 25 == 0 or number == len(claim_ids):
            print(
                f"  {number}/{len(claim_ids)} claims, {chunk_count} chunks, {finding_count} findings so far"
            )
    return {
        "claims": len(claim_ids),
        "chunks": chunk_count,
        "findings": finding_count,
        "warnings": warnings,
    }


if __name__ == "__main__":
    from src.graph.connection import open_neo4j_driver

    arguments = sys.argv[1:]
    if not arguments:
        print("Give claim IDs, for example C-1088, or --all. See the top of this file.")
        raise SystemExit(1)
    driver = open_neo4j_driver()
    try:
        summary = load_pdfs_into_graph(
            driver, None if arguments == ["--all"] else arguments
        )
    except (RuntimeError, ValueError) as problem:
        print(f"Error: {problem}")
        raise SystemExit(1)
    finally:
        driver.close()
    print(
        f"Done: {summary['claims']} claims, {summary['chunks']} chunks, {summary['findings']} findings, "
        f"{len(summary['warnings'])} warnings."
    )
