"""V3 tests: fake tables v2 and ground truth (PLAN-v2.md A4).

The tests write to a temporary folder, not to data/. They contain their OWN simple version
of each table rule (BI-5, BI-6, BF-1 to BF-4, CT-1 to CT-4, CT-7), written from the rule
descriptions, so they check the generator from the outside.
"""

import csv
import datetime
import json
from collections import Counter

import pytest

from src import config
from src.datagen.make_tables import LOOKALIKE_GROUPS, TABLE_NAMES, generate_tables
from src.documents.feature_catalog import FEATURES_BY_CODE

TEST_SEED = 42
TABLE_RULES = ["BI-5", "BI-6", "BF-1", "BF-2", "BF-3", "BF-4", "CT-1", "CT-2", "CT-3", "CT-4", "CT-7"]

# (table, column, target table, target column, may the value be empty?)
FOREIGN_KEYS = [
    ("claimants", "address_id", "addresses", "address_id", False),
    ("claims", "claimant_id", "claimants", "claimant_id", False),
    ("claims", "policy_id", "policies", "policy_id", False),
    ("claims", "vehicle_id", "vehicles", "vehicle_id", False),
    ("claims", "incident_id", "incidents", "incident_id", False),
    ("claims", "repair_shop_id", "providers", "provider_id", True),   # passengers have no repair
    ("claims", "clinic_id", "providers", "provider_id", False),
    ("claims", "attorney_id", "attorneys", "attorney_id", True),
    ("attorneys", "law_firm_id", "law_firms", "law_firm_id", False),
    ("treatments", "claim_id", "claims", "claim_id", False),
    ("treatments", "provider_id", "providers", "provider_id", False),
    ("reserve_events", "claim_id", "claims", "claim_id", False),
    ("payments", "claim_id", "claims", "claim_id", False),
    ("lawsuits", "claim_id", "claims", "claim_id", False),
    ("lawsuits", "court_id", "courts", "court_id", False),
    ("lawsuits", "plaintiff_law_firm_id", "law_firms", "law_firm_id", False),
    ("lawsuits", "expert_id", "experts", "expert_id", False),
    ("settlements", "lawsuit_id", "lawsuits", "lawsuit_id", False),
]


def read_table(tables_dir, table_name):
    with open(tables_dir / f"{table_name}.csv", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def day(text):
    return datetime.date.fromisoformat(text) if text else None


@pytest.fixture(scope="module")
def output_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("run_one")
    generate_tables(TEST_SEED, folder / "tables", folder / "ground_truth.json")
    return folder


@pytest.fixture(scope="module")
def tables(output_dir):
    return {table_name: read_table(output_dir / "tables", table_name) for table_name in TABLE_NAMES}


@pytest.fixture(scope="module")
def truth(output_dir):
    with open(output_dir / "ground_truth.json", encoding="utf-8") as json_file:
        return json.load(json_file)


def fired_table_rules(tables):
    """{claim ID: set of table rules that fire}, straight from the CSV text."""
    visits, reserves, payments = {}, {}, {}
    for row in tables["treatments"]:
        visits.setdefault(row["claim_id"], []).append(day(row["visit_date"]))
    for row in tables["reserve_events"]:
        reserves.setdefault(row["claim_id"], []).append((day(row["event_date"]), float(row["reserve_total"])))
    for row in tables["payments"]:
        payments.setdefault(row["claim_id"], []).append((day(row["payment_date"]), float(row["amount"]),
                                                         row["payment_type"]))
    policies = {row["policy_id"]: row for row in tables["policies"]}
    lawsuits = {row["claim_id"]: row for row in tables["lawsuits"]}
    fired = {}
    for claim in tables["claims"]:
        claim_id, loss = claim["claim_id"], day(claim["loss_date"])
        rules = set()
        claim_visits = sorted(visits.get(claim_id, []))
        if claim["attorney_retained_date"] and claim_visits and day(claim["attorney_retained_date"]) < claim_visits[0]:
            rules.add("BI-5")
        if sum(1 for visit in claim_visits if 0 <= (visit - loss).days <= 30) > 12:
            rules.add("BI-6")
        events = sorted(reserves.get(claim_id, []))
        for first_index, (first_date, first_total) in enumerate(events):
            for second_date, second_total in events[first_index + 1:]:
                if (second_date - first_date).days <= 30 and second_total > 1.5 * first_total:
                    rules.add("BF-1")
        claim_payments = sorted(payments.get(claim_id, []))
        if events and sum(amount for _, amount, _ in claim_payments) >= 1.5 * events[-1][1]:
            rules.add("BF-2")
        for index in range(len(claim_payments) - 2):
            if (claim_payments[index + 2][0] - claim_payments[index][0]).days <= 14:
                rules.add("BF-3")
        repair_paid = sum(amount for _, amount, kind in claim_payments if kind == "repair")
        if claim["repair_estimate_amount"] and repair_paid >= 1.5 * float(claim["repair_estimate_amount"]):
            rules.add("BF-4")
        policy = policies[claim["policy_id"]]
        if (loss - day(policy["customer_since"])).days < 30:
            rules.add("CT-1")
        if policy["last_coverage_increase_date"] and 0 <= (loss - day(policy["last_coverage_increase_date"])).days <= 30:
            rules.add("CT-2")
        in_lapse = policy["lapse_start"] and day(policy["lapse_start"]) <= loss <= day(policy["lapse_end"])
        if loss < day(policy["effective_date"]) or loss > day(policy["expiration_date"]) or in_lapse:
            rules.add("CT-3")
        if (day(claim["reported_date"]) - loss).days > 30:
            rules.add("CT-4")
        lawsuit = lawsuits.get(claim_id)
        if lawsuit and 0 <= (day(lawsuit["limitation_deadline"]) - day(lawsuit["filed_date"])).days <= 30:
            rules.add("CT-7")
        fired[claim_id] = rules
    return fired


def test_counts_match_the_plan(tables, truth):
    assert len(tables["claims"]) == config.TOTAL_CLAIMS
    assert 45 <= len(tables["lawsuits"]) <= 55
    for fraud_type, size in config.FRAUD_TYPE_SIZES.items():
        assert len(truth["fraud_types"][fraud_type]) == size
    fraud_count = sum(1 for claim in truth["claims"].values() if claim["is_fraud"])
    assert fraud_count == 60 and 0.10 <= fraud_count / config.TOTAL_CLAIMS <= 0.14
    lookalikes = truth["lookalike_groups"]
    assert sum(len(claim_ids) for claim_ids in lookalikes.values()) >= 100
    assert len(lookalikes["family"]) >= 16
    for group in ["busy_law_firm", "busy_repair_shop", "large_clinic"]:
        assert len(lookalikes[group]) >= 25
    minimums = {"late_reporter": 15, "new_customer": 10, "serious_injury": 10, "pre_existing": 10}
    for group, minimum in minimums.items():
        assert len(lookalikes[group]) >= minimum
    lawsuit_claim_ids = {row["claim_id"] for row in tables["lawsuits"]}
    assert set(truth["fraud_types"]["ring_c"]) <= lawsuit_claim_ids


def test_every_foreign_id_exists(tables):
    for table, column, target_table, target_column, may_be_empty in FOREIGN_KEYS:
        known_ids = {row[target_column] for row in tables[target_table]}
        for row in tables[table]:
            if row[column] == "" and may_be_empty:
                continue
            assert row[column] in known_ids, f"{table}.{column} = '{row[column]}' not found in {target_table}"


def test_each_table_rule_fires_exactly_on_its_planted_claims(tables, truth):
    fired = fired_table_rules(tables)
    for rule_id in TABLE_RULES:
        planted = {claim_id for claim_id, claim in truth["claims"].items() if rule_id in claim["planted_rules"]}
        really_fired = {claim_id for claim_id, rules in fired.items() if rule_id in rules}
        assert planted, f"{rule_id} is planted on no claim"
        assert really_fired == planted, (rule_id, sorted(planted ^ really_fired)[:5])


def test_honest_firing_rate_of_each_table_rule_is_on_target(tables, truth):
    fired = fired_table_rules(tables)
    claim_rows = {row["claim_id"]: row for row in tables["claims"]}
    lawsuit_claim_ids = {row["claim_id"] for row in tables["lawsuits"]}
    ordinary = [claim_id for claim_id, claim in truth["claims"].items() if claim["group"] == "ordinary"]
    for rule_id in TABLE_RULES:
        population = []
        for claim_id in ordinary:
            row = claim_rows[claim_id]
            if rule_id == "BI-5" and not row["attorney_id"]:
                continue
            if rule_id == "BF-4" and not row["repair_estimate_amount"]:
                continue
            if rule_id == "CT-7" and claim_id not in lawsuit_claim_ids:
                continue
            population.append(claim_id)
        rate = sum(1 for claim_id in population if rule_id in fired[claim_id]) / len(population)
        target = config.HONEST_RULE_RATES[rule_id]
        assert 0.02 <= target <= 0.12
        assert abs(rate - target) <= 1 / len(population) + 1e-9, (rule_id, rate, target)


def test_ground_truth_profiles_splits_and_demo_claims(truth):
    claims = truth["claims"]
    for claim_id, claim in claims.items():
        assert claim["split"] in ["tuning", "test"]
        for code, value in claim["planted_features"].items():
            feature = FEATURES_BY_CODE[code]
            if feature.value_type == "rating":
                assert value in feature.ratings, (claim_id, code, value)
            else:
                assert isinstance(value, int) and value >= 1
    for fraud_type, claim_ids in truth["fraud_types"].items():
        assert {claims[claim_id]["split"] for claim_id in claim_ids} == {"tuning", "test"}, fraud_type
    demo = truth["demo_claims"]
    assert claims[demo["ring"]]["fraud_type"] == "ring_a"
    assert claims[demo["lookalike"]]["lookalike_group"] in LOOKALIKE_GROUPS
    assert claims[demo["build_up"]]["fraud_type"] == "build_up"


def test_lookalikes_look_like_fraud_but_plant_no_strong_network_rule(tables, truth):
    claims = truth["claims"]
    for group in ["family", "multi_claimant_incident", "busy_law_firm", "busy_repair_shop", "large_clinic"]:
        for claim_id in truth["lookalike_groups"][group]:
            assert not {"NL-3", "NL-4", "NL-6"} & set(claims[claim_id]["planted_rules"]), (group, claim_id)
    claim_rows = {row["claim_id"]: row for row in tables["claims"]}
    claimants = {row["claimant_id"]: row for row in tables["claimants"]}
    incident_sizes = Counter(row["incident_id"] for row in tables["claims"])
    multi_incidents = {claim_rows[claim_id]["incident_id"] for claim_id in truth["lookalike_groups"]["multi_claimant_incident"]}
    assert len(multi_incidents) >= 10
    for claim_id in truth["lookalike_groups"]["multi_claimant_incident"]:
        size = incident_sizes[claim_rows[claim_id]["incident_id"]]
        assert 2 <= size <= 4 and size <= claims[claim_id]["planted_features"]["occupants_listed"]
    for claim_id in truth["lookalike_groups"]["family"]:
        person = claimants[claim_rows[claim_id]["claimant_id"]]
        relatives = [other for other in truth["lookalike_groups"]["family"] if other != claim_id
                     and claimants[claim_rows[other]["claimant_id"]]["address_id"] == person["address_id"]]
        assert len(relatives) == 1
        relative = claimants[claim_rows[relatives[0]]["claimant_id"]]
        assert relative["phone_number"] == person["phone_number"] and relative["last_name"] == person["last_name"]
        assert relative["date_of_birth"] != person["date_of_birth"]
        assert claim_rows[relatives[0]]["incident_id"] != claim_rows[claim_id]["incident_id"]


def test_same_seed_gives_identical_files(output_dir, tmp_path):
    generate_tables(TEST_SEED, tmp_path / "tables", tmp_path / "ground_truth.json")
    first_files = sorted((output_dir / "tables").glob("*.csv"))
    assert len(first_files) == len(TABLE_NAMES) == 16
    for first_file in first_files:
        assert first_file.read_bytes() == (tmp_path / "tables" / first_file.name).read_bytes(), first_file.name
    assert (output_dir / "ground_truth.json").read_bytes() == (tmp_path / "ground_truth.json").read_bytes()
