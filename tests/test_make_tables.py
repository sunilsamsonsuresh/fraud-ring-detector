"""Step 2 tests: fake tables and ground truth.

The tests write to a temporary folder, not to data/.
"""

import csv
import datetime
import json

import pytest

from src.datagen.make_tables import generate_tables

TEST_SEED = 42

# (table, column, target table, target column, may the value be empty?)
FOREIGN_KEYS = [
    ("claimants", "address_id", "addresses", "address_id", False),
    ("claims", "claimant_id", "claimants", "claimant_id", False),
    ("claims", "policy_id", "policies", "policy_id", False),
    ("claims", "vehicle_id", "vehicles", "vehicle_id", False),
    ("claims", "repair_shop_id", "providers", "provider_id", True),   # passengers have no repair
    ("claims", "clinic_id", "providers", "provider_id", False),
    ("claims", "attorney_id", "attorneys", "attorney_id", True),      # not every claimant has a lawyer
    ("attorneys", "law_firm_id", "law_firms", "law_firm_id", False),
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


@pytest.fixture(scope="module")
def output_dir(tmp_path_factory):
    """Generate the data once and share it with all tests in this file."""
    folder = tmp_path_factory.mktemp("run_one")
    generate_tables(TEST_SEED, folder / "tables", folder / "ground_truth.json")
    return folder


@pytest.fixture(scope="module")
def ground_truth(output_dir):
    with open(output_dir / "ground_truth.json", encoding="utf-8") as json_file:
        return json.load(json_file)


def test_counts_match_plan(output_dir, ground_truth):
    assert len(read_table(output_dir / "tables", "claims")) == 500
    assert 45 <= len(read_table(output_dir / "tables", "lawsuits")) <= 55

    ring_sizes = {}
    for ring in ground_truth["rings"]:
        ring_sizes[ring["ring_id"]] = len(ring["claim_ids"])
    assert ring_sizes == {"A": 12, "B": 15, "C": 10}
    assert len(ground_truth["innocent_overlaps"]) >= 10


def test_every_foreign_id_exists(output_dir):
    tables_dir = output_dir / "tables"
    for table, column, target_table, target_column, may_be_empty in FOREIGN_KEYS:
        known_ids = set()
        for row in read_table(tables_dir, target_table):
            known_ids.add(row[target_column])
        for row in read_table(tables_dir, table):
            value = row[column]
            if value == "" and may_be_empty:
                continue
            assert value in known_ids, f"{table}.{column} = '{value}' not found in {target_table}"


def test_claim_providers_have_the_right_type(output_dir):
    tables_dir = output_dir / "tables"
    provider_type_by_id = {}
    for row in read_table(tables_dir, "providers"):
        provider_type_by_id[row["provider_id"]] = row["type"]
    for claim in read_table(tables_dir, "claims"):
        if claim["repair_shop_id"] != "":
            assert provider_type_by_id[claim["repair_shop_id"]] == "repair_shop"
        assert provider_type_by_id[claim["clinic_id"]] == "clinic"


def test_only_planted_groups_share_a_phone(output_dir, ground_truth):
    """No accidental shared phones: a shared phone must belong to Ring A or a family."""
    tables_dir = output_dir / "tables"
    claimant_by_id = {}
    for row in read_table(tables_dir, "claimants"):
        claimant_by_id[row["claimant_id"]] = row

    claim_ids_by_phone = {}
    for claim in read_table(tables_dir, "claims"):
        phone = claimant_by_id[claim["claimant_id"]]["phone_number"]
        claim_ids_by_phone.setdefault(phone, []).append(claim["claim_id"])

    allowed_claim_ids = set(ground_truth["rings"][0]["claim_ids"])  # Ring A
    for overlap in ground_truth["innocent_overlaps"]:
        if overlap["kind"] == "family":
            allowed_claim_ids.update(overlap["claim_ids"])

    for phone, claim_ids in claim_ids_by_phone.items():
        if len(claim_ids) > 1:
            for claim_id in claim_ids:
                assert claim_id in allowed_claim_ids, f"Unplanned shared phone {phone}"


def test_ring_c_files_just_before_the_deadline(output_dir, ground_truth):
    ring_c_claim_ids = set(ground_truth["rings"][2]["claim_ids"])
    ring_c_lawsuits = []
    for lawsuit in read_table(output_dir / "tables", "lawsuits"):
        if lawsuit["claim_id"] in ring_c_claim_ids:
            ring_c_lawsuits.append(lawsuit)

    assert len(ring_c_lawsuits) == 10
    for lawsuit in ring_c_lawsuits:
        filed = datetime.date.fromisoformat(lawsuit["filed_date"])
        deadline = datetime.date.fromisoformat(lawsuit["limitation_deadline"])
        assert 1 <= (deadline - filed).days <= 10


def test_same_seed_gives_identical_files(output_dir, tmp_path):
    generate_tables(TEST_SEED, tmp_path / "tables", tmp_path / "ground_truth.json")

    first_files = sorted((output_dir / "tables").glob("*.csv"))
    assert len(first_files) == 13
    for first_file in first_files:
        second_file = tmp_path / "tables" / first_file.name
        assert first_file.read_bytes() == second_file.read_bytes(), f"{first_file.name} differs"
    assert (output_dir / "ground_truth.json").read_bytes() == (tmp_path / "ground_truth.json").read_bytes()
