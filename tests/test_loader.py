"""Step 4 tests: the graph in Neo4j matches the CSV tables.

Needs Neo4j running and the tables in data/tables (generate-data --tables).
The expected counts come straight from the CSV files, not from loader code.
"""

import csv
import json

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.graph.loader import load_graph

NODE_TABLES = {
    "Address": "addresses", "Claimant": "claimants", "Policy": "policies", "Vehicle": "vehicles",
    "Claim": "claims", "Provider": "providers", "Attorney": "attorneys", "LawFirm": "law_firms",
    "Lawsuit": "lawsuits", "Court": "courts", "Expert": "experts", "Payment": "payments",
}
# edge type -> (table, column whose non-empty values each make one edge)
EDGE_COLUMNS = {
    "FILED": ("claims", "claimant_id"), "UNDER": ("claims", "policy_id"),
    "INVOLVES": ("claims", "vehicle_id"), "LIVES_AT": ("claimants", "address_id"),
    "HAS_PHONE": ("claimants", "phone_number"), "REPAIRED_AT": ("claims", "repair_shop_id"),
    "TREATED_BY": ("claims", "clinic_id"), "REPRESENTED_BY": ("claims", "attorney_id"),
    "WORKS_AT": ("attorneys", "law_firm_id"), "LED_TO": ("lawsuits", "claim_id"),
    "FILED_IN": ("lawsuits", "court_id"), "PLAINTIFF_COUNSEL": ("lawsuits", "plaintiff_law_firm_id"),
    "USES_EXPERT": ("lawsuits", "expert_id"), "HAS_PAYMENT": ("payments", "claim_id"),
}

CLAIMS_USING_PHONE = """
MATCH (:Phone {number: $number})<-[:HAS_PHONE]-(:Claimant)-[:FILED]->(claim:Claim)
RETURN claim.claim_id AS claim_id
"""
COUNT_SETTLED_LAWSUITS = "MATCH (lawsuit:Lawsuit) WHERE lawsuit.settlement_amount IS NOT NULL RETURN count(*) AS count"


def read_table(table_name):
    with open(config.TABLES_DIR / f"{table_name}.csv", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


@pytest.fixture(scope="module")
def loaded_counts():
    """Load twice. Return both results so the tests can compare them."""
    first_counts = load_graph(config.TABLES_DIR)
    second_counts = load_graph(config.TABLES_DIR)
    return first_counts, second_counts


def test_node_counts_match_the_csv_files(loaded_counts):
    node_counts, _ = loaded_counts[1]
    for label, table_name in NODE_TABLES.items():
        assert node_counts[label] == len(read_table(table_name)), f"{label} count is wrong"
    distinct_phones = set()
    for claimant in read_table("claimants"):
        distinct_phones.add(claimant["phone_number"])
    assert node_counts["Phone"] == len(distinct_phones)


def test_edge_counts_match_the_csv_files(loaded_counts):
    _, edge_counts = loaded_counts[1]
    for edge_type, (table_name, column) in EDGE_COLUMNS.items():
        expected = 0
        for row in read_table(table_name):
            if row[column] != "":
                expected += 1
        assert edge_counts[edge_type] == expected, f"{edge_type} count is wrong"


def test_loading_twice_gives_the_same_counts(loaded_counts):
    first_counts, second_counts = loaded_counts
    assert first_counts == second_counts


def test_settlements_are_stored_on_lawsuits(loaded_counts):
    driver = open_neo4j_driver()
    try:
        records, _, _ = driver.execute_query(COUNT_SETTLED_LAWSUITS)
    finally:
        driver.close()
    assert records[0]["count"] == len(read_table("settlements"))


def test_ring_a_phones_link_only_ring_a_claims(loaded_counts):
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        ring_a = json.load(file)["rings"][0]
    driver = open_neo4j_driver()
    try:
        for phone_number in ring_a["key_entities"]["phone_numbers"]:
            records, _, _ = driver.execute_query(CLAIMS_USING_PHONE, number=phone_number)
            claim_ids = [record["claim_id"] for record in records]
            assert len(claim_ids) == 4
            for claim_id in claim_ids:
                assert claim_id in ring_a["claim_ids"]
    finally:
        driver.close()
