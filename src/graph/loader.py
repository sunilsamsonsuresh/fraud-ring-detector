"""Load the CSV tables into Neo4j (PLAN.md, Step 4).

Rule: one CSV row makes one node, and each foreign ID makes one edge.
All queries use MERGE, so running the loader twice gives the same graph.

Main flow:
1. Read every CSV file.
2. Make sure the schema (constraints and indexes) exists.
3. Load the nodes, table by table.
4. Load the edges, one edge type at a time.
5. Count nodes and edges in Neo4j and return the counts.
"""

import csv

from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.graph.schema import create_schema

TABLE_NAMES = ["addresses", "claimants", "policies", "vehicles", "claims", "providers", "attorneys",
               "law_firms", "lawsuits", "settlements", "courts", "experts", "payments"]

# (query, table it reads). Phones have no table: the claimants table holds the numbers.
NODE_LOADS = [
    (queries.LOAD_ADDRESSES, "addresses"),
    (queries.LOAD_PHONES, "claimants"),
    (queries.LOAD_CLAIMANTS, "claimants"),
    (queries.LOAD_POLICIES, "policies"),
    (queries.LOAD_VEHICLES, "vehicles"),
    (queries.LOAD_CLAIMS, "claims"),
    (queries.LOAD_PROVIDERS, "providers"),
    (queries.LOAD_ATTORNEYS, "attorneys"),
    (queries.LOAD_LAW_FIRMS, "law_firms"),
    (queries.LOAD_LAWSUITS, "lawsuits"),
    (queries.LOAD_SETTLEMENTS_ONTO_LAWSUITS, "settlements"),   # after the lawsuits exist
    (queries.LOAD_COURTS, "courts"),
    (queries.LOAD_EXPERTS, "experts"),
    (queries.LOAD_PAYMENTS, "payments"),
]

# (query, table, column of the "from" node ID, column of the "to" node ID)
EDGE_LOADS = [
    (queries.LINK_CLAIMANT_FILED_CLAIM, "claims", "claimant_id", "claim_id"),
    (queries.LINK_CLAIM_UNDER_POLICY, "claims", "claim_id", "policy_id"),
    (queries.LINK_CLAIM_INVOLVES_VEHICLE, "claims", "claim_id", "vehicle_id"),
    (queries.LINK_CLAIMANT_LIVES_AT_ADDRESS, "claimants", "claimant_id", "address_id"),
    (queries.LINK_CLAIMANT_HAS_PHONE, "claimants", "claimant_id", "phone_number"),
    (queries.LINK_CLAIM_REPAIRED_AT_PROVIDER, "claims", "claim_id", "repair_shop_id"),
    (queries.LINK_CLAIM_TREATED_BY_PROVIDER, "claims", "claim_id", "clinic_id"),
    (queries.LINK_CLAIM_REPRESENTED_BY_ATTORNEY, "claims", "claim_id", "attorney_id"),
    (queries.LINK_ATTORNEY_WORKS_AT_LAW_FIRM, "attorneys", "attorney_id", "law_firm_id"),
    (queries.LINK_CLAIM_LED_TO_LAWSUIT, "lawsuits", "claim_id", "lawsuit_id"),
    (queries.LINK_LAWSUIT_FILED_IN_COURT, "lawsuits", "lawsuit_id", "court_id"),
    (queries.LINK_LAWSUIT_PLAINTIFF_COUNSEL, "lawsuits", "lawsuit_id", "plaintiff_law_firm_id"),
    (queries.LINK_LAWSUIT_USES_EXPERT, "lawsuits", "lawsuit_id", "expert_id"),
    (queries.LINK_CLAIM_HAS_PAYMENT, "payments", "claim_id", "payment_id"),
]


def read_tables(tables_dir):
    tables = {}
    for table_name in TABLE_NAMES:
        file_path = tables_dir / f"{table_name}.csv"
        if not file_path.exists():
            raise FileNotFoundError(f"{file_path} is missing. Run: python main.py generate-data --tables")
        with open(file_path, newline="", encoding="utf-8") as csv_file:
            tables[table_name] = list(csv.DictReader(csv_file))
    return tables


def make_id_pairs(rows, from_column, to_column):
    """Turn rows into [{from_id, to_id}, ...]. An empty ID (for example, no attorney) means no edge."""
    pairs = []
    for row in rows:
        if row[from_column] != "" and row[to_column] != "":
            pairs.append({"from_id": row[from_column], "to_id": row[to_column]})
    return pairs


def count_graph(driver):
    """Return ({label: count}, {edge type: count}) as they are in Neo4j now."""
    node_counts = {}
    records, _, _ = driver.execute_query(queries.COUNT_NODES_BY_LABEL)
    for record in records:
        node_counts[record["label"]] = record["count"]
    edge_counts = {}
    records, _, _ = driver.execute_query(queries.COUNT_EDGES_BY_TYPE)
    for record in records:
        edge_counts[record["edge_type"]] = record["count"]
    return node_counts, edge_counts


def load_graph(tables_dir):
    """Load all tables into Neo4j. Return (node counts, edge counts) after the load."""
    tables = read_tables(tables_dir)
    driver = open_neo4j_driver()
    try:
        create_schema(driver)
        for query, table_name in NODE_LOADS:
            driver.execute_query(query, rows=tables[table_name])
        for query, table_name, from_column, to_column in EDGE_LOADS:
            pairs = make_id_pairs(tables[table_name], from_column, to_column)
            driver.execute_query(query, pairs=pairs)
        return count_graph(driver)
    finally:
        driver.close()
