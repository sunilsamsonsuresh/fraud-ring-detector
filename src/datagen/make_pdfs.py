"""Make the fake PDFs for each claim (PLAN.md, Step 3).

Main flow:
1. Read the CSV tables and ground_truth.json (made in Step 2).
2. Pick the claims: all of them, the given --claim-ids, or the first --limit.
3. For each claim: collect its facts from the tables, decide if it has a
   police report and if that report gets a planted wrong date, then build
   each document.
4. Write documents.csv (one row per PDF) and planted_conflicts.csv.

Each claim gets its own random generator, seeded with the seed and the
claim ID. So a claim's PDFs are the same in a 5-claim run and a full run.
"""

import csv
import datetime
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.datagen.claim_documents import (
    RING_A_STORY_PROMPT, RING_B_NOTE_PROMPT, get_ring_template, make_adjuster_file,
    make_attorney_letter, make_fnol, make_medical_records, make_police_report, make_repair_estimate,
)
from src.datagen.lawsuit_documents import (
    RING_C_COMPLAINT_PROMPT, RING_C_DEMAND_PROMPT, make_complaint, make_defense_answer,
    make_demand_letter, make_deposition, make_settlement_agreement,
)

CLAIM_DOCUMENT_BUILDERS = [make_fnol, make_police_report, make_repair_estimate,
                           make_medical_records, make_attorney_letter, make_adjuster_file]
LAWSUIT_DOCUMENT_BUILDERS = [make_complaint, make_demand_letter, make_defense_answer,
                             make_deposition, make_settlement_agreement]
TABLES_NEEDED = ["claims", "claimants", "addresses", "policies", "vehicles", "providers",
                 "attorneys", "law_firms", "lawsuits", "courts", "experts", "settlements"]

NO_POLICE_REPORT_CHANCE = 0.2   # police do not always come; never for parking lot collisions
DATE_CONFLICT_CHANCE = 0.08     # share of police reports with a planted wrong crash date


def read_csv_rows(file_path):
    with open(file_path, newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def rows_by_id(rows, id_column):
    index = {}
    for row in rows:
        index[row[id_column]] = row
    return index


def load_tables(tables_dir):
    tables = {}
    for table_name in TABLES_NEEDED:
        file_path = tables_dir / f"{table_name}.csv"
        if not file_path.exists():
            raise FileNotFoundError(f"{file_path} is missing. Run: python main.py generate-data --tables")
        tables[table_name] = read_csv_rows(file_path)
    return tables


def load_ring_ids(ground_truth_file):
    with open(ground_truth_file, encoding="utf-8") as json_file:
        ground_truth = json.load(json_file)
    ring_id_by_claim = {}
    for ring in ground_truth["rings"]:
        for claim_id in ring["claim_ids"]:
            ring_id_by_claim[claim_id] = ring["ring_id"]
    return ring_id_by_claim


def collect_claim_facts(claim, indexes, ring_id_by_claim):
    """Join the rows that belong to one claim into one dict."""
    attorney = indexes["attorneys"].get(claim["attorney_id"])          # "" gives None
    lawsuit = indexes["lawsuit_by_claim"].get(claim["claim_id"])
    facts = {
        "claim": claim,
        "claimant": indexes["claimants"][claim["claimant_id"]],
        "policy": indexes["policies"][claim["policy_id"]],
        "vehicle": indexes["vehicles"][claim["vehicle_id"]],
        "repair_shop": indexes["providers"].get(claim["repair_shop_id"]),
        "clinic": indexes["providers"][claim["clinic_id"]],
        "attorney": attorney,
        "law_firm": indexes["law_firms"][attorney["law_firm_id"]] if attorney else None,
        "lawsuit": lawsuit,
        "court": indexes["courts"][lawsuit["court_id"]] if lawsuit else None,
        "expert": indexes["experts"][lawsuit["expert_id"]] if lawsuit else None,
        "settlement": indexes["settlement_by_lawsuit"].get(lawsuit["lawsuit_id"]) if lawsuit else None,
        "ring_id": ring_id_by_claim.get(claim["claim_id"]),
    }
    facts["address"] = indexes["addresses"][facts["claimant"]["address_id"]]
    return facts


def plan_police_report(facts, rng):
    """Decide if there is a police report and if its crash date is planted wrong.
    Return the planted conflict as a dict, or None."""
    claim = facts["claim"]
    loss_date = datetime.date.fromisoformat(claim["loss_date"])
    facts["police_loss_date"] = loss_date
    facts["has_police_report"] = (claim["accident_type"] != "parking lot collision"
                                  and rng.random() >= NO_POLICE_REPORT_CHANCE)
    if facts["has_police_report"] and rng.random() < DATE_CONFLICT_CHANCE:
        facts["police_loss_date"] = loss_date + datetime.timedelta(days=rng.choice([-3, -2, -1, 1, 2, 3]))
        return {"claim_id": claim["claim_id"], "document_id": f"{claim['claim_id']}-police_report",
                "field": "loss_date", "table_value": loss_date.isoformat(),
                "document_value": facts["police_loss_date"].isoformat()}
    return None


def select_claims(claims, claim_ids, limit):
    selected = claims
    if claim_ids:
        known_ids = {claim["claim_id"] for claim in claims}
        unknown_ids = [claim_id for claim_id in claim_ids if claim_id not in known_ids]
        if unknown_ids:
            raise ValueError(f"Unknown claim IDs: {', '.join(unknown_ids)}")
        selected = [claim for claim in claims if claim["claim_id"] in claim_ids]
    if limit is not None:
        selected = selected[:limit]
    return selected


def write_rows(file_path, rows, column_names):
    with open(file_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=column_names)
        writer.writeheader()
        writer.writerows(rows)


def prepare_shared_ring_texts():
    """Fetch the 4 shared ring texts before the workers start, so two workers
    never pay for the same text at the same time."""
    for prompt in [RING_A_STORY_PROMPT, RING_B_NOTE_PROMPT, RING_C_COMPLAINT_PROMPT, RING_C_DEMAND_PROMPT]:
        get_ring_template(prompt)


def make_claim_documents(claim, seed, indexes, ring_id_by_claim, pdfs_dir):
    """Build every PDF of one claim. Return (document rows, planted conflict or None)."""
    rng = random.Random(f"{seed}-{claim['claim_id']}")
    facts = collect_claim_facts(claim, indexes, ring_id_by_claim)
    conflict = plan_police_report(facts, rng)

    builders = list(CLAIM_DOCUMENT_BUILDERS)
    if facts["lawsuit"] is not None:
        builders.extend(LAWSUIT_DOCUMENT_BUILDERS)
    document_rows = []
    for builder in builders:
        row = builder(facts, rng, pdfs_dir / claim["claim_id"])
        if row is not None:
            document_rows.append(row)
    return document_rows, conflict


def run_claims_in_parallel(claims, seed, indexes, ring_id_by_claim, pdfs_dir, workers):
    """Run make_claim_documents for many claims at the same time.

    A thread pool keeps `workers` claims busy at once. Most of the time is spent
    waiting for the LLM, so threads give a big speed-up. A failed claim does not
    stop the others; its error is returned so the caller can report it.
    """
    result_by_claim_id = {}
    error_by_claim_id = {}
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        claim_id_by_future = {}
        for claim in claims:
            future = pool.submit(make_claim_documents, claim, seed, indexes, ring_id_by_claim, pdfs_dir)
            claim_id_by_future[future] = claim["claim_id"]

        # as_completed gives each future as soon as its claim is done.
        for finished_count, future in enumerate(as_completed(claim_id_by_future), start=1):
            claim_id = claim_id_by_future[future]
            try:
                result_by_claim_id[claim_id] = future.result()
            except RuntimeError as error:
                error_by_claim_id[claim_id] = str(error)
                print(f"  [{finished_count}/{len(claims)}] {claim_id}: FAILED - {error}")
                continue
            print(f"  [{finished_count}/{len(claims)}] {claim_id}: {len(result_by_claim_id[claim_id][0])} documents")
    finally:
        # On Ctrl+C: drop the claims that have not started. Saved LLM answers stay in the cache.
        pool.shutdown(wait=True, cancel_futures=True)
    return result_by_claim_id, error_by_claim_id


def generate_pdfs(seed, tables_dir, ground_truth_file, pdfs_dir, claim_ids=None, limit=None, workers=1):
    """Make the PDFs. Return a summary dict with counts and any failed claims."""
    tables = load_tables(tables_dir)
    ring_id_by_claim = load_ring_ids(ground_truth_file)
    indexes = {
        "claimants": rows_by_id(tables["claimants"], "claimant_id"),
        "addresses": rows_by_id(tables["addresses"], "address_id"),
        "policies": rows_by_id(tables["policies"], "policy_id"),
        "vehicles": rows_by_id(tables["vehicles"], "vehicle_id"),
        "providers": rows_by_id(tables["providers"], "provider_id"),
        "attorneys": rows_by_id(tables["attorneys"], "attorney_id"),
        "law_firms": rows_by_id(tables["law_firms"], "law_firm_id"),
        "courts": rows_by_id(tables["courts"], "court_id"),
        "experts": rows_by_id(tables["experts"], "expert_id"),
        "lawsuit_by_claim": rows_by_id(tables["lawsuits"], "claim_id"),
        "settlement_by_lawsuit": rows_by_id(tables["settlements"], "lawsuit_id"),
    }

    selected_claims = select_claims(tables["claims"], claim_ids, limit)
    prepare_shared_ring_texts()
    result_by_claim_id, error_by_claim_id = run_claims_in_parallel(
        selected_claims, seed, indexes, ring_id_by_claim, pdfs_dir, workers)

    # Put the results back in claim order, so the output files do not depend on
    # which worker finished first.
    document_rows = []
    conflict_rows = []
    for claim in selected_claims:
        if claim["claim_id"] in result_by_claim_id:
            claim_document_rows, conflict = result_by_claim_id[claim["claim_id"]]
            document_rows.extend(claim_document_rows)
            if conflict is not None:
                conflict_rows.append(conflict)

    pdfs_dir.mkdir(parents=True, exist_ok=True)
    write_rows(pdfs_dir / "documents.csv", document_rows,
               ["document_id", "claim_id", "document_type", "file_name", "page_count"])
    write_rows(pdfs_dir / "planted_conflicts.csv", conflict_rows,
               ["claim_id", "document_id", "field", "table_value", "document_value"])

    page_total = 0
    for row in document_rows:
        page_total += row["page_count"]
    return {"documents": len(document_rows), "pages": page_total, "planted_conflicts": len(conflict_rows),
            "failed_claims": error_by_claim_id}
