"""The ingest-documents command: run the Intake agent on many claims and sum up.

Step 7 will add chunks and embeddings to this command.
"""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed

from src import config
from src.agents.intake import intake


def all_document_rows():
    documents_file = config.PDFS_DIR / "documents.csv"
    if not documents_file.exists():
        raise RuntimeError(f"{documents_file} is missing. Run: python main.py generate-data --pdfs")
    with open(documents_file, newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def select_claims(claim_ids=None, limit=None):
    """Return (claim IDs to read, their number of PDF pages). Raises ValueError for an unknown ID."""
    rows = all_document_rows()
    known_claim_ids = []
    for row in rows:
        if row["claim_id"] not in known_claim_ids:
            known_claim_ids.append(row["claim_id"])
    if claim_ids:
        for claim_id in claim_ids:
            if claim_id not in known_claim_ids:
                raise ValueError(f"Claim {claim_id} has no documents in documents.csv.")
        selected = list(claim_ids)
    else:
        selected = known_claim_ids[:limit] if limit else known_claim_ids
    page_count = 0
    for row in rows:
        if row["claim_id"] in selected:
            page_count += int(row["page_count"])
    return selected, page_count


def ingest_documents(claim_ids, workers=1):
    """Run Intake on each claim, `workers` claims at the same time. Return (results by claim, errors by claim)."""
    result_by_claim_id = {}
    error_by_claim_id = {}
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        claim_id_by_future = {}
        for claim_id in claim_ids:
            claim_id_by_future[pool.submit(intake, {"claim_id": claim_id})] = claim_id
        for finished_count, future in enumerate(as_completed(claim_id_by_future), start=1):
            claim_id = claim_id_by_future[future]
            try:
                result = future.result()
            except RuntimeError as error:
                error_by_claim_id[claim_id] = str(error)
                print(f"  [{finished_count}/{len(claim_ids)}] {claim_id}: FAILED - {error}")
                continue
            if "error_message" in result:
                error_by_claim_id[claim_id] = result["error_message"]
                print(f"  [{finished_count}/{len(claim_ids)}] {claim_id}: FAILED - {result['error_message']}")
                continue
            result_by_claim_id[claim_id] = result
            print(f"  [{finished_count}/{len(claim_ids)}] {claim_id}: {result['documents_read']} documents")
    finally:
        pool.shutdown(wait=True, cancel_futures=True)   # on Ctrl+C: drop the claims not started yet
    return result_by_claim_id, error_by_claim_id


def print_summary(result_by_claim_id):
    matched_by_type = {}
    total_by_type = {}
    count_by_method = {}
    unmatched, conflicts, warnings = [], [], []
    for claim_id in sorted(result_by_claim_id):
        result = result_by_claim_id[claim_id]
        for entity in result["entity_results"]:
            if entity["status"] == "not_in_graph":
                continue
            entity_type = entity["entity_type"]
            total_by_type[entity_type] = total_by_type.get(entity_type, 0) + 1
            if entity["status"] == "matched":
                matched_by_type[entity_type] = matched_by_type.get(entity_type, 0) + 1
                count_by_method[entity["match_method"]] = count_by_method.get(entity["match_method"], 0) + 1
            else:
                unmatched.append(entity)
        conflicts.extend(result["document_conflicts"])
        warnings.extend(result["intake_warnings"])

    total = sum(total_by_type.values())
    matched = sum(matched_by_type.values())
    print(f"\nMatch rate: {matched} of {total} entities ({100 * matched / max(total, 1):.1f}%)")
    for entity_type in sorted(total_by_type):
        print(f"  {entity_type:<16} {matched_by_type.get(entity_type, 0):>4} of {total_by_type[entity_type]:>4}")
    print("Match methods: " + ", ".join(f"{method} {count}" for method, count in sorted(count_by_method.items())))

    print(f"\nUnmatched entities ({len(unmatched)}):")
    for entity in unmatched:
        print(f"  {entity['document_id']} p{entity['page_number']}  {entity['entity_type']:<14} "
              f"'{entity['value_as_written']}' - {entity['reason']}")
    print(f"\nConflicts between PDFs and tables ({len(conflicts)}):")
    for conflict in conflicts:
        print(f"  {conflict['document_id']} p{conflict['page_number']}  {conflict['field']}: "
              f"table {conflict['table_value']}, document '{conflict['document_value']}'")
    print(f"\nWarnings ({len(warnings)}):")
    for warning in warnings:
        print(f"  {warning}")
