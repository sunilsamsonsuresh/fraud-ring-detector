"""V5 tests: the v2 tables in Neo4j (PLAN-v2.md V5).

Needs Neo4j and the v2 tables in data/tables (python main.py generate-data --tables).
The graph must hold only table data: the test loads it twice and compares the counts with
the CSV files. (Documents, chunks and findings come in V6 and would change the counts.)
"""

import csv
import json

import pytest

from src import config
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.graph.loader import TABLE_NAMES, load_graph


def read_tables():
    tables = {}
    for table_name in TABLE_NAMES:
        file_path = config.TABLES_DIR / f"{table_name}.csv"
        if not file_path.exists():
            pytest.skip("No v2 tables. Run: python main.py generate-data --tables")
        with open(file_path, newline="", encoding="utf-8") as csv_file:
            tables[table_name] = list(csv.DictReader(csv_file))
    if "incident_id" not in tables["claims"][0]:
        pytest.skip("data/tables holds v1 tables")
    return tables


def count_rows_with(rows, *columns):
    return sum(1 for row in rows if all(row[column] != "" for column in columns))


def expected_counts(tables):
    nodes = {"Claimant": len(tables["claimants"]), "Claim": len(tables["claims"]),
             "Policy": len(tables["policies"]), "Vehicle": len(tables["vehicles"]),
             "Address": len(tables["addresses"]),
             "Phone": len({row["phone_number"] for row in tables["claimants"]}),
             "Provider": len(tables["providers"]), "Attorney": len(tables["attorneys"]),
             "LawFirm": len(tables["law_firms"]), "Lawsuit": len(tables["lawsuits"]),
             "Court": len(tables["courts"]), "Expert": len(tables["experts"]),
             "Payment": len(tables["payments"]), "Incident": len(tables["incidents"]),
             "Treatment": len(tables["treatments"]), "ReserveEvent": len(tables["reserve_events"])}
    claims = tables["claims"]
    edges = {"FILED": len(claims), "UNDER": len(claims), "INVOLVES": len(claims),
             "LIVES_AT": len(tables["claimants"]), "HAS_PHONE": len(tables["claimants"]),
             "REPAIRED_AT": count_rows_with(claims, "repair_shop_id"), "TREATED_BY": len(claims),
             "REPRESENTED_BY": count_rows_with(claims, "attorney_id"), "WORKS_AT": len(tables["attorneys"]),
             "LED_TO": len(tables["lawsuits"]), "FILED_IN": len(tables["lawsuits"]),
             "PLAINTIFF_COUNSEL": len(tables["lawsuits"]), "USES_EXPERT": len(tables["lawsuits"]),
             "HAS_PAYMENT": len(tables["payments"]), "ARISES_FROM": len(claims),
             "HAS_TREATMENT": len(tables["treatments"]), "BY_PROVIDER": len(tables["treatments"]),
             "HAS_RESERVE_EVENT": len(tables["reserve_events"])}
    return nodes, edges


@pytest.fixture(scope="module")
def loaded():
    tables = read_tables()
    first_counts = load_graph(config.TABLES_DIR)
    second_counts = load_graph(config.TABLES_DIR)
    return tables, first_counts, second_counts


def test_node_and_edge_counts_match_the_csv_files(loaded):
    tables, (node_counts, edge_counts), _ = loaded
    expected_nodes, expected_edges = expected_counts(tables)
    assert node_counts == expected_nodes
    assert edge_counts == expected_edges


def test_a_second_load_gives_the_same_counts(loaded):
    _, first_counts, second_counts = loaded
    assert first_counts == second_counts


def test_new_properties_have_real_types(loaded):
    tables, _, _ = loaded
    claim = next(row for row in tables["claims"] if row["attorney_retained_date"] and row["close_date"])
    driver = open_neo4j_driver()
    try:
        records, _, _ = driver.execute_query(
            "MATCH (claim:Claim {claim_id: $claim_id})-[:UNDER]->(policy:Policy) "
            "RETURN claim.attorney_retained_date AS retained, claim.close_date AS closed, "
            "policy.customer_since AS customer_since, policy.per_accident_limit AS limit", claim_id=claim["claim_id"])
    finally:
        driver.close()
    record = records[0]
    assert record["retained"].iso_format() == claim["attorney_retained_date"]
    assert record["closed"].iso_format() == claim["close_date"]
    assert record["customer_since"] is not None and isinstance(record["limit"], int)


def test_an_honest_multi_claimant_incident_joins_its_claims(loaded):
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        truth = json.load(file)
    tables, _, _ = loaded
    incident_by_claim = {row["claim_id"]: row["incident_id"] for row in tables["claims"]}
    group = truth["lookalike_groups"]["multi_claimant_incident"]
    incident_id = incident_by_claim[group[0]]
    expected = sorted(claim_id for claim_id in group if incident_by_claim[claim_id] == incident_id)
    driver = open_neo4j_driver()
    try:
        records, _, _ = driver.execute_query(queries.CLAIMS_OF_INCIDENT, incident_id=incident_id)
    finally:
        driver.close()
    assert [record["claim_id"] for record in records] == expected
    assert 2 <= len(expected) <= 4
