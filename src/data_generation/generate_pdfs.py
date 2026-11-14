"""Make the fake PDFs of each claim. This is the runner of the PDF generators.

Main flow:
1. Read the CSV tables and ground_truth.json (the profile of each claim, made by generate_tables.py).
2. Pick the claims: all of them, the given claim IDs, or the first N.
3. For each claim: join its facts and its profile, set the crash date of the police report
   (a planted loss date conflict moves it 1 to 3 days), then build each document.
4. Write documents.csv (one row per PDF) and planted_conflicts.csv (the moved crash dates).

Each claim gets its own random generator, seeded with the seed and the claim ID.
So the PDFs of a claim are the same in a 5-claim run and in a full run.
The LLM writes only the free text. Every answer is cached in data/cache/, so a second run costs nothing.

Run:  .venv/bin/python -m src.data_generation.generate_pdfs --limit 5 --data-dir <folder>
"""

import argparse
import csv
import datetime
import json
import random
from pathlib import Path

from src import config
from src.data_generation.make_fnol_and_attorney_letter import (
    make_attorney_letter,
    make_fnol,
)
from src.data_generation.make_lawsuit_documents import (
    make_complaint,
    make_defense_answer,
    make_demand_letter,
    make_deposition,
    make_settlement_agreement,
)
from src.data_generation.make_medical_records_and_adjuster_file import (
    make_adjuster_file,
    make_medical_records,
)
from src.data_generation.make_police_report_and_repair_estimate import (
    make_police_report,
    make_repair_estimate,
)

# Each builder returns one row for documents.csv, or None when the claim has no such document.
CLAIM_DOCUMENT_BUILDERS = [
    make_fnol,
    make_police_report,
    make_repair_estimate,
    make_medical_records,
    make_attorney_letter,
    make_adjuster_file,
]
LAWSUIT_DOCUMENT_BUILDERS = [
    make_complaint,
    make_demand_letter,
    make_defense_answer,
    make_deposition,
    make_settlement_agreement,
]
TABLES_NEEDED = [
    "claims",
    "claimants",
    "addresses",
    "policies",
    "vehicles",
    "providers",
    "attorneys",
    "law_firms",
    "lawsuits",
    "courts",
    "experts",
    "settlements",
    "incidents",
    "treatments",
]


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
            raise FileNotFoundError(
                f"{file_path} is missing. Run: python -m src.data_generation.generate_tables"
            )
        tables[table_name] = read_csv_rows(file_path)
    return tables


def load_profiles(ground_truth_file):
    """{claim ID: profile} from the ground truth file."""
    if not ground_truth_file.exists():
        raise FileNotFoundError(
            f"{ground_truth_file} is missing. Run: python -m src.data_generation.generate_tables"
        )
    with open(ground_truth_file, encoding="utf-8") as json_file:
        ground_truth = json.load(json_file)
    return ground_truth["claims"]


def build_indexes(tables):
    """Dicts to find a row by its ID, so the claim facts can be joined without searching lists."""
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
        "treatments_by_claim": {},
        "claims_by_incident": {},
    }
    for visit in tables["treatments"]:
        indexes["treatments_by_claim"].setdefault(visit["claim_id"], []).append(visit)
    for claim in tables["claims"]:
        claimant = indexes["claimants"][claim["claimant_id"]]
        indexes["claims_by_incident"].setdefault(claim["incident_id"], []).append(
            {
                "claim_id": claim["claim_id"],
                "first_name": claimant["first_name"],
                "last_name": claimant["last_name"],
            }
        )
    return indexes


def collect_claim_facts(claim, indexes, profiles, seed):
    """Join the rows and the profile that belong to one claim into one dict."""
    attorney = indexes["attorneys"].get(claim["attorney_id"])  # "" gives None
    lawsuit = indexes["lawsuit_by_claim"].get(claim["claim_id"])
    incident = indexes["incidents"][claim["incident_id"]]
    facts = {
        "seed": seed,
        "profile": profiles[claim["claim_id"]],
        "profiles": profiles,
        "claim": dict(claim, location_text=incident["location_text"]),
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
        "settlement": indexes["settlement_by_lawsuit"].get(lawsuit["lawsuit_id"])
        if lawsuit
        else None,
        "treatments": sorted(
            indexes["treatments_by_claim"][claim["claim_id"]],
            key=lambda visit: visit["visit_date"],
        ),
        "incident_claims": indexes["claims_by_incident"][claim["incident_id"]],
    }
    facts["address"] = indexes["addresses"][facts["claimant"]["address_id"]]
    return facts


def set_police_crash_date(facts, rng):
    """The police crash date is the real loss date, unless the profile planted a conflict (rule AS-7).
    Return the planted conflict as a dict, or None."""
    claim = facts["claim"]
    loss_date = datetime.date.fromisoformat(claim["loss_date"])
    facts["police_loss_date"] = loss_date
    if facts["profile"]["has_police_report"] and facts["profile"]["loss_date_conflict"]:
        facts["police_loss_date"] = loss_date + datetime.timedelta(
            days=rng.choice([-3, -2, -1, 1, 2, 3])
        )
        return {
            "claim_id": claim["claim_id"],
            "document_id": f"{claim['claim_id']}-police_report",
            "field": "loss_date",
            "table_value": loss_date.isoformat(),
            "document_value": facts["police_loss_date"].isoformat(),
        }
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


def generate_pdfs(
    seed, tables_dir, ground_truth_file, pdfs_dir, claim_ids=None, limit=None
):
    """Make the PDFs. Return a summary dict with counts and the claims that failed.

    A claim that fails (for example the LLM call fails) does not stop the others."""
    tables = load_tables(tables_dir)
    profiles = load_profiles(ground_truth_file)
    indexes = build_indexes(tables)
    selected_claims = select_claims(tables["claims"], claim_ids, limit)

    document_rows = []
    conflict_rows = []
    failed_claims = {}
    for number, claim in enumerate(selected_claims, start=1):
        try:
            claim_document_rows, conflict = make_claim_documents(
                claim, seed, indexes, profiles, pdfs_dir
            )
        except RuntimeError as error:
            failed_claims[claim["claim_id"]] = str(error)
            print(
                f"  [{number}/{len(selected_claims)}] {claim['claim_id']}: FAILED - {error}"
            )
            continue
        document_rows.extend(claim_document_rows)
        if conflict is not None:
            conflict_rows.append(conflict)
        print(
            f"  [{number}/{len(selected_claims)}] {claim['claim_id']}: {len(claim_document_rows)} documents"
        )

    pdfs_dir.mkdir(parents=True, exist_ok=True)
    write_rows(
        pdfs_dir / "documents.csv",
        document_rows,
        ["document_id", "claim_id", "document_type", "file_name", "page_count"],
    )
    write_rows(
        pdfs_dir / "planted_conflicts.csv",
        conflict_rows,
        ["claim_id", "document_id", "field", "table_value", "document_value"],
    )

    page_total = 0
    for row in document_rows:
        page_total += row["page_count"]
    return {
        "documents": len(document_rows),
        "pages": page_total,
        "planted_conflicts": len(conflict_rows),
        "failed_claims": failed_claims,
    }


def facts_for_one_claim(claim_id, data_dir=config.DATA_DIR, seed=config.RANDOM_SEED):
    """(facts, rng) of one claim, ready for one document builder. The debug snippets of the builder files use it."""
    tables = load_tables(data_dir / "tables")
    profiles = load_profiles(data_dir / "ground_truth.json")
    indexes = build_indexes(tables)
    claim = select_claims(tables["claims"], [claim_id], None)[0]
    rng = random.Random(f"{seed}-{claim_id}")
    facts = collect_claim_facts(claim, indexes, profiles, seed)
    set_police_crash_date(facts, rng)
    return facts, rng


def main():
    parser = argparse.ArgumentParser(description="Make the fake PDFs of the claims.")
    parser.add_argument(
        "--data-dir",
        default=str(config.DATA_DIR),
        help="Folder with tables/ and ground_truth.json. The PDFs go to its pdfs/ folder.",
    )
    parser.add_argument(
        "--claim-ids", help="Only these claims, comma separated. Example: C-1003,C-1006"
    )
    parser.add_argument(
        "--limit", type=int, help="Only the first N claims (for a small test)."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow the run to replace an existing documents.csv.",
    )
    arguments = parser.parse_args()

    data_dir = Path(arguments.data_dir)
    pdfs_dir = data_dir / "pdfs"
    if (pdfs_dir / "documents.csv").exists() and not arguments.overwrite:
        print(f"{pdfs_dir / 'documents.csv'} exists. Nothing was changed.")
        print(
            "Use another --data-dir, or add --overwrite if you really want to replace these PDFs."
        )
        return
    claim_ids = arguments.claim_ids.split(",") if arguments.claim_ids else None
    try:
        summary = generate_pdfs(
            config.RANDOM_SEED,
            data_dir / "tables",
            data_dir / "ground_truth.json",
            pdfs_dir,
            claim_ids,
            arguments.limit,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Could not make the PDFs: {error}")
        return
    print(summary)


if __name__ == "__main__":
    main()
