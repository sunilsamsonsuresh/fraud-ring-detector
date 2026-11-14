"""Make the fake CSV tables and ground_truth.json. This is the runner of the table generators.

Main flow:
1. Plan the claims (claim_plan_blocks.py, plan_fraud_claims.py, plan_honest_claims.py):
   the world (shops, clinics, law firms, experts) and one plan per claim: fraud types,
   lookalikes, ordinary claims, and network noise among the ordinary claims.
2. Add the signals (plan_signals_and_features.py): base-rate noise with exact counts, and the
   feature values of each claim.
3. Shuffle the plans, so no claim ID gives away a group.
4. Write every row from the plans (write_claim_rows.py, write_policy_and_lawsuit_rows.py).
5. Compute which network rules really fire (compute_network_truth.py).
6. Write the CSV files and ground_truth.json (per claim: group, split, planted features and rules).

The same seed gives the same files. All randomness comes from one seeded Faker object.

Run:  .venv/bin/python -m src.data_generation.generate_tables --data-dir <folder>
"""

import argparse
import csv
import json
from pathlib import Path

from faker import Faker

from src import config
from src.data_generation.claim_plan_blocks import assign_partners, make_world
from src.data_generation.compute_network_truth import compute_structural_rules
from src.data_generation.plan_fraud_claims import plan_all_fraud
from src.data_generation.plan_honest_claims import plan_honest_claims
from src.data_generation.plan_signals_and_features import (
    STRUCTURAL_RULES,
    add_base_rate_noise,
    choose_features,
    set_occupant_counts,
)
from src.data_generation.table_row_helpers import DATA_AS_OF_DATE
from src.data_generation.write_claim_rows import write_all_rows
from src.scoring.rules_catalog import RULES

TABLE_NAMES = [
    "incidents",
    "claimants",
    "addresses",
    "policies",
    "vehicles",
    "claims",
    "treatments",
    "reserve_events",
    "payments",
    "providers",
    "attorneys",
    "law_firms",
    "lawsuits",
    "courts",
    "experts",
    "settlements",
]
LOOKALIKE_GROUPS = [
    "family",
    "multi_claimant_incident",
    "busy_law_firm",
    "busy_repair_shop",
    "large_clinic",
    "late_reporter",
    "new_customer",
    "serious_injury",
    "pre_existing",
    "jump_in_co_claimant",
]
RULE_ORDER = [rule.rule_id for rule in RULES]


def generate_tables(seed, tables_dir, ground_truth_file):
    """Write all CSV files and the ground truth. Return {table name: row count}."""
    fake = Faker("en_US")
    fake.seed_instance(seed)
    tables = {table_name: [] for table_name in TABLE_NAMES}

    world = make_world(fake, tables)
    plans = plan_all_fraud(fake, world)
    plans.extend(plan_honest_claims(fake, world, len(plans)))
    assign_partners(fake, world, plans)
    set_occupant_counts(fake, plans)
    add_base_rate_noise(fake, [plan for plan in plans if plan["group"] == "ordinary"])
    for plan in plans:
        plan["features"] = choose_features(fake, plan)

    fake.random.shuffle(plans)
    write_all_rows(fake, tables, plans)
    occupants_by_claim = {
        plan["claim_id"]: plan["incident"]["occupants_listed"]
        for plan in plans
        if plan["incident"]["has_police_report"]
    }
    story_group_by_claim = {plan["claim_id"]: plan["story_group"] for plan in plans}
    structural_rules = compute_structural_rules(
        tables, occupants_by_claim, story_group_by_claim
    )

    ground_truth = build_ground_truth(fake, seed, world, plans, structural_rules)
    write_csv_files(tables, tables_dir)
    write_json_file(ground_truth, ground_truth_file)
    return {table_name: len(tables[table_name]) for table_name in TABLE_NAMES}


def planted_rules_of(plan, structural_rules):
    """The intended non-network rules plus the network rules that really fire, in catalog order."""
    rule_ids = set()
    for rule_id in plan["signals"]:
        if rule_id not in STRUCTURAL_RULES:
            rule_ids.add(rule_id)
    rule_ids.update(structural_rules[plan["claim_id"]])
    return [rule_id for rule_id in RULE_ORDER if rule_id in rule_ids]


def assign_splits(fake, plans):
    """Half of each group goes to "tuning", the other half to "test". Every group is in both."""
    claim_ids_by_group = {}
    for plan in plans:
        claim_ids_by_group.setdefault(plan["group"], []).append(plan["claim_id"])
    split_by_claim = {}
    for group in sorted(claim_ids_by_group):
        claim_ids = sorted(claim_ids_by_group[group])
        fake.random.shuffle(claim_ids)
        tuning_count = (len(claim_ids) + 1) // 2
        for position, claim_id in enumerate(claim_ids):
            split_by_claim[claim_id] = "tuning" if position < tuning_count else "test"
    return split_by_claim


def pick_demo_claim(claims, group):
    """The claim of the group with the most planted rules (lowest claim ID on a tie)."""
    candidates = sorted(
        claim_id for claim_id, truth in claims.items() if truth["group"] == group
    )
    best = candidates[0]
    for claim_id in candidates:
        if len(claims[claim_id]["planted_rules"]) > len(claims[best]["planted_rules"]):
            best = claim_id
    return best


def build_ground_truth(fake, seed, world, plans, structural_rules):
    split_by_claim = assign_splits(fake, plans)
    claims = {}
    for plan in sorted(plans, key=lambda plan: plan["claim_id"]):
        planted_rules = planted_rules_of(plan, structural_rules)
        claims[plan["claim_id"]] = {
            "group": plan["group"],
            "is_fraud": plan["is_fraud"],
            "fraud_type": plan["fraud_type"],
            "lookalike_group": plan["group"]
            if plan["group"] in LOOKALIKE_GROUPS
            else None,
            "split": split_by_claim[plan["claim_id"]],
            "role": plan["role"],
            "has_police_report": plan["incident"]["has_police_report"],
            "story_group": plan["story_group"],
            "loss_date_conflict": "AS-7" in planted_rules,
            "planted_features": plan["features"],
            "planted_rules": planted_rules,
        }
    groups = {}
    for claim_id, truth in claims.items():
        groups.setdefault(truth["group"], []).append(claim_id)
    return {
        "version": 2,
        "seed": seed,
        "data_as_of_date": DATA_AS_OF_DATE.isoformat(),
        "fraud_types": {
            fraud_type: groups[fraud_type] for fraud_type in config.FRAUD_TYPE_SIZES
        },
        "lookalike_groups": {group: groups[group] for group in LOOKALIKE_GROUPS},
        "key_entities": {
            "ring_a": {"repair_shop_id": world["ring_a_repair_shop_id"]},
            "ring_b": {
                "clinic_id": world["ring_b_clinic_id"],
                "law_firm_id": world["ring_b_law_firm_id"],
                "attorney_id": world["ring_b_attorney_ids"][0],
            },
            "ring_c": {
                "law_firm_id": world["ring_c_law_firm_id"],
                "expert_id": world["ring_c_expert_id"],
            },
        },
        "demo_claims": {
            "ring": pick_demo_claim(claims, "ring_a"),
            "lookalike": pick_demo_claim(claims, "family"),
            "build_up": pick_demo_claim(claims, "build_up"),
        },
        "honest_rule_rates": config.HONEST_RULE_RATES,
        "notes": [
            (
                "planted_rules: the intended rules, plus AS-6 and NL-1 to NL-6 computed from the tables "
                "(src/data_generation/compute_network_truth.py)."
            ),
            "A repeat claimant's claims share a phone, so they are strongly linked (NL-1) as well as NL-2.",
            (
                "story_group: claims in one group get the same story text in V4. ring_c copies the complaint "
                "and demand letter wording; the other groups copy the claimant's account of the accident."
            ),
        ],
        "claims": claims,
    }


def write_csv_files(tables, tables_dir):
    tables_dir.mkdir(parents=True, exist_ok=True)
    for table_name, rows in tables.items():
        if len(rows) == 0:
            raise ValueError(
                f"Table '{table_name}' has no rows. The generator has a bug."
            )
        with open(
            tables_dir / f"{table_name}.csv", "w", newline="", encoding="utf-8"
        ) as csv_file:
            # DictWriter writes each dict as one line. None becomes an empty cell; a date becomes 2024-03-05.
            writer = csv.DictWriter(csv_file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def write_json_file(data, file_path):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Make the fake CSV tables and the ground truth."
    )
    parser.add_argument(
        "--data-dir",
        default=str(config.DATA_DIR),
        help="The tables go to its tables/ folder, the ground truth to ground_truth.json.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow the run to replace existing tables.",
    )
    arguments = parser.parse_args()

    data_dir = Path(arguments.data_dir)
    if (data_dir / "tables" / "claims.csv").exists() and not arguments.overwrite:
        print(f"{data_dir / 'tables' / 'claims.csv'} exists. Nothing was changed.")
        print(
            "Use another --data-dir, or add --overwrite if you really want to replace these tables."
        )
        return
    try:
        row_counts = generate_tables(
            config.RANDOM_SEED, data_dir / "tables", data_dir / "ground_truth.json"
        )
    except (OSError, ValueError) as error:
        print(f"Could not make the tables: {error}")
        return
    for table_name, row_count in row_counts.items():
        print(f"  {table_name}: {row_count} rows")


if __name__ == "__main__":
    main()
