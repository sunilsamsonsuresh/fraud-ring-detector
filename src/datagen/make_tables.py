"""Make the fake CSV tables and ground_truth.json (PLAN.md, Step 2).

Main flow:
1. Make one seeded Faker object. All randomness comes from it.
2. Add the reference rows: courts, experts, repair shops, clinics, law firms.
3. Plan all 500 claims: rings, innocent overlaps, normal claims.
4. Shuffle the plans, so ring claims get mixed claim IDs.
5. Turn each plan into rows. Write the CSV files and the ground truth.
"""

import csv
import json

from faker import Faker

from src.datagen.claim_rows import add_claim_rows
from src.datagen.plant_patterns import FAMILY_SIZES, add_reference_entities, plan_all_claims

TABLE_NAMES = [
    "claimants", "addresses", "policies", "vehicles", "claims", "providers", "attorneys",
    "law_firms", "payments", "lawsuits", "courts", "experts", "settlements",
]
FIRST_CLAIM_NUMBER = 1001


def generate_tables(seed, tables_dir, ground_truth_file):
    """Write all CSV files and the ground truth. Return {table name: row count}."""
    fake = Faker("en_US")
    fake.seed_instance(seed)

    tables = {}
    for table_name in TABLE_NAMES:
        tables[table_name] = []
    used_phone_numbers = set()

    entities = add_reference_entities(fake, tables, used_phone_numbers)
    plans = plan_all_claims(fake, tables, entities, used_phone_numbers)
    fake.random.shuffle(plans)

    claim_ids_by_group = {}
    for position, plan in enumerate(plans):
        claim_id = f"C-{FIRST_CLAIM_NUMBER + position}"
        add_claim_rows(fake, tables, claim_id, plan, used_phone_numbers)
        if plan["group"] not in claim_ids_by_group:
            claim_ids_by_group[plan["group"]] = []
        claim_ids_by_group[plan["group"]].append(claim_id)

    ground_truth = build_ground_truth(seed, entities, plans, claim_ids_by_group)
    write_csv_files(tables, tables_dir)
    write_json_file(ground_truth, ground_truth_file)

    row_counts = {}
    for table_name in TABLE_NAMES:
        row_counts[table_name] = len(tables[table_name])
    return row_counts


def unique_plan_values(plans, group, field):
    """Return the sorted, distinct values of one field in one group of plans."""
    values = set()
    for plan in plans:
        if plan["group"] == group:
            values.add(plan[field])
    return sorted(values)


def build_ground_truth(seed, entities, plans, claim_ids_by_group):
    rings = [
        {
            "ring_id": "A",
            "name": "Staged accident ring",
            "pattern": "Shared phones and addresses. Same repair shop. Same city, short time window, same accident type.",
            "claim_ids": claim_ids_by_group["ring_a"],
            "key_entities": {
                "repair_shop_id": entities["ring_a_repair_shop_id"],
                "phone_numbers": unique_plan_values(plans, "ring_a", "phone_number"),
                "address_ids": unique_plan_values(plans, "ring_a", "address_id"),
            },
        },
        {
            "ring_id": "B",
            "name": "Clinic and law firm mill",
            "pattern": "One clinic and one law firm. Same injury, about 25 visits, medical bills near 8,500.",
            "claim_ids": claim_ids_by_group["ring_b"],
            "key_entities": {
                "clinic_id": entities["ring_b_clinic_id"],
                "law_firm_id": entities["ring_b_law_firm_id"],
            },
        },
        {
            "ring_id": "C",
            "name": "Litigation ring",
            "pattern": "All in lawsuits. Same law firm and expert. Filed 1-10 days before the deadline. Demands near 75,000.",
            "claim_ids": claim_ids_by_group["ring_c"],
            "key_entities": {
                "law_firm_id": entities["ring_c_law_firm_id"],
                "expert_id": entities["ring_c_expert_id"],
            },
        },
    ]

    innocent_overlaps = []
    for family_number in range(1, len(FAMILY_SIZES) + 1):
        group = f"family_{family_number}"
        innocent_overlaps.append({
            "overlap_id": group,
            "kind": "family",
            "description": "Family members in one car. They share an address, a phone, a policy and a vehicle.",
            "claim_ids": claim_ids_by_group[group],
            "key_entities": {
                "address_id": unique_plan_values(plans, group, "address_id")[0],
                "phone_number": unique_plan_values(plans, group, "phone_number")[0],
            },
        })
    innocent_overlaps.append({
        "overlap_id": "busy_law_firm",
        "kind": "busy_law_firm",
        "description": "A busy but honest law firm with many clients. Normal clinics, shops and lawsuit timing.",
        "claim_ids": claim_ids_by_group["busy_law_firm"],
        "key_entities": {"law_firm_id": entities["busy_law_firm_id"]},
    })
    innocent_overlaps.append({
        "overlap_id": "popular_repair_shop",
        "kind": "popular_repair_shop",
        "description": "A popular repair shop with many unrelated claims.",
        "claim_ids": claim_ids_by_group["popular_repair_shop"],
        "key_entities": {"repair_shop_id": entities["popular_repair_shop_id"]},
    })
    innocent_overlaps.append({
        "overlap_id": "large_clinic",
        "kind": "large_clinic",
        "description": "A large clinic near a busy road. Many patients with normal, varied treatment.",
        "claim_ids": claim_ids_by_group["large_clinic"],
        "key_entities": {"clinic_id": entities["large_clinic_id"]},
    })

    return {"seed": seed, "rings": rings, "innocent_overlaps": innocent_overlaps}


def write_csv_files(tables, tables_dir):
    tables_dir.mkdir(parents=True, exist_ok=True)
    for table_name, rows in tables.items():
        if len(rows) == 0:
            raise ValueError(f"Table '{table_name}' has no rows. The generator has a bug.")
        file_path = tables_dir / f"{table_name}.csv"
        with open(file_path, "w", newline="", encoding="utf-8") as csv_file:
            # DictWriter writes each dict as one line. None becomes an empty cell.
            writer = csv.DictWriter(csv_file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def write_json_file(data, file_path):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=2)
