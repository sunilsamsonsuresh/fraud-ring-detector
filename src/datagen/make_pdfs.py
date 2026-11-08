"""Make the fake PDFs for each claim (PLAN.md Step 3, PLAN-v2.md V4).

Main flow:
1. Read the CSV tables and the v2 ground_truth.json (each claim's profile, made in V3).
2. Pick the claims: all of them, the given --claim-ids, or the first --limit.
3. Fetch the shared story texts once (story groups: copied stories and copied court wording).
4. For each claim: collect its facts and profile, set the police crash date (a planted
   loss date conflict moves it 1 to 3 days), then build each document.
5. Write documents.csv (one row per PDF) and planted_conflicts.csv.

Each claim gets its own random generator, seeded with the seed and the claim ID.
So a claim's PDFs are the same in a 5-claim run and a full run.
"""

import csv
import datetime
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.datagen.care_documents import make_adjuster_file, make_medical_records
from src.datagen.claim_documents import get_ring_template, make_attorney_letter, make_fnol, story_prompt_for
from src.datagen.incident_documents import make_police_report, make_repair_estimate
from src.datagen.lawsuit_documents import (
    RING_C_COMPLAINT_PROMPT, RING_C_DEMAND_PROMPT, make_complaint, make_defense_answer,
    make_demand_letter, make_deposition, make_settlement_agreement,
)

CLAIM_DOCUMENT_BUILDERS = [make_fnol, make_police_report, make_repair_estimate,
                           make_medical_records, make_attorney_letter, make_adjuster_file]
LAWSUIT_DOCUMENT_BUILDERS = [make_complaint, make_demand_letter, make_defense_answer,
                             make_deposition, make_settlement_agreement]
TABLES_NEEDED = ["claims", "claimants", "addresses", "policies", "vehicles", "providers", "attorneys",
                 "law_firms", "lawsuits", "courts", "experts", "settlements", "incidents", "treatments"]


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


def load_profiles(ground_truth_file):
    """{claim ID: profile} from the v2 ground truth."""
    with open(ground_truth_file, encoding="utf-8") as json_file:
        ground_truth = json.load(json_file)
    if ground_truth.get("version") != 2:
        raise ValueError(f"{ground_truth_file} is not a v2 ground truth. Run: python main.py generate-data --tables")
    return ground_truth["claims"]


def build_indexes(tables):
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
        "incidents": rows_by_id(tables["incidents"], "incident_id"),
        "lawsuit_by_claim": rows_by_id(tables["lawsuits"], "claim_id"),
        "settlement_by_lawsuit": rows_by_id(tables["settlements"], "lawsuit_id"),
        "treatments_by_claim": {}, "claims_by_incident": {},
    }
    for visit in tables["treatments"]:
        indexes["treatments_by_claim"].setdefault(visit["claim_id"], []).append(visit)
    for claim in tables["claims"]:
        claimant = indexes["claimants"][claim["claimant_id"]]
        indexes["claims_by_incident"].setdefault(claim["incident_id"], []).append({
            "claim_id": claim["claim_id"], "first_name": claimant["first_name"], "last_name": claimant["last_name"]})
    return indexes


def collect_claim_facts(claim, indexes, profiles, seed):
    """Join the rows and the profile that belong to one claim into one dict."""
    attorney = indexes["attorneys"].get(claim["attorney_id"])          # "" gives None
    lawsuit = indexes["lawsuit_by_claim"].get(claim["claim_id"])
    incident = indexes["incidents"][claim["incident_id"]]
    facts = {
        "seed": seed, "profile": profiles[claim["claim_id"]], "profiles": profiles,
        "claim": dict(claim, location_text=incident["location_text"]),   # a copy: threads share the rows
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
        "treatments": sorted(indexes["treatments_by_claim"][claim["claim_id"]], key=lambda visit: visit["visit_date"]),
        "incident_claims": indexes["claims_by_incident"][claim["incident_id"]],
    }
    facts["address"] = indexes["addresses"][facts["claimant"]["address_id"]]
    return facts


def set_police_crash_date(facts, rng):
    """The police crash date is the real loss date, unless the profile planted a conflict (AS-7).
    Return the planted conflict as a dict, or None."""
    claim = facts["claim"]
    loss_date = datetime.date.fromisoformat(claim["loss_date"])
    facts["police_loss_date"] = loss_date
    if facts["profile"]["has_police_report"] and facts["profile"]["loss_date_conflict"]:
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


def prepare_shared_story_texts(claims, profiles):
    """Fetch every shared story text the selected claims need, one at a time, before the
    workers start, so two workers never pay for the same text at the same time."""
    prompts = []
    for claim in claims:
        story_group = profiles[claim["claim_id"]]["story_group"]
        if story_group == "ring_c":
            needed = [RING_C_COMPLAINT_PROMPT, RING_C_DEMAND_PROMPT]
        elif story_group:
            needed = [story_prompt_for(story_group, claim["accident_type"])]
        else:
            needed = []
        for prompt in needed:
            if prompt not in prompts:
                prompts.append(prompt)
    for prompt in prompts:
        get_ring_template(prompt)


def make_claim_documents(claim, seed, indexes, profiles, pdfs_dir):
    """Build every PDF of one claim. Return (document rows, planted conflict or None)."""
    rng = random.Random(f"{seed}-{claim['claim_id']}")
    facts = collect_claim_facts(claim, indexes, profiles, seed)
    conflict = set_police_crash_date(facts, rng)

    builders = list(CLAIM_DOCUMENT_BUILDERS)
    if facts["lawsuit"] is not None:
        builders.extend(LAWSUIT_DOCUMENT_BUILDERS)
    document_rows = []
    for builder in builders:
        row = builder(facts, rng, pdfs_dir / claim["claim_id"])
        if row is not None:
            document_rows.append(row)
    return document_rows, conflict


def run_claims_in_parallel(claims, seed, indexes, profiles, pdfs_dir, workers):
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
            future = pool.submit(make_claim_documents, claim, seed, indexes, profiles, pdfs_dir)
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
    profiles = load_profiles(ground_truth_file)
    indexes = build_indexes(tables)

    selected_claims = select_claims(tables["claims"], claim_ids, limit)
    prepare_shared_story_texts(selected_claims, profiles)
    result_by_claim_id, error_by_claim_id = run_claims_in_parallel(
        selected_claims, seed, indexes, profiles, pdfs_dir, workers)

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
