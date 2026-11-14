"""Step 2 of loading the graph: put the CSV tables into Neo4j as nodes and links.

Rule: one CSV row makes one node. Each ID that points to another table makes one link (edge).
Example: the row of claim C-1001 has a policy_id. That makes a (Claim)-[:UNDER]->(Policy) edge.

The flow:
1. Read the 16 CSV files of data/tables/ (made by the data generator).
2. Create the schema (graph_schema.py). Constraints must exist before the first node.
3. Load the nodes, table by table. The queries are in table_loading_queries.py.
4. Load the edges, one kind of edge at a time. The nodes must exist first.
5. Count the nodes and the edges in Neo4j, and return the counts.

Every query uses MERGE, so you can run this file many times: the second run gives the same graph.
"""

import csv

from neo4j import Driver

from src import config
from src.data_loading import table_loading_queries as queries
from src.data_loading.graph_schema import create_graph_schema

TABLE_NAMES = [
    "addresses",
    "claimants",
    "policies",
    "vehicles",
    "claims",
    "providers",
    "attorneys",
    "law_firms",
    "lawsuits",
    "settlements",
    "courts",
    "experts",
    "payments",
    "incidents",
    "treatments",
    "reserve_events",
]

# (query, the table it reads). Phones have no table: the claimants table holds the numbers.
# The order matters: the settlements go onto lawsuits, so lawsuits come first.
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
    (queries.LOAD_SETTLEMENTS_ONTO_LAWSUITS, "settlements"),
    (queries.LOAD_COURTS, "courts"),
    (queries.LOAD_EXPERTS, "experts"),
    (queries.LOAD_PAYMENTS, "payments"),
    (queries.LOAD_INCIDENTS, "incidents"),
    (queries.LOAD_TREATMENTS, "treatments"),
    (queries.LOAD_RESERVE_EVENTS, "reserve_events"),
]

# (query, the table it reads, the column with the ID of the "from" node, the column with the ID of the "to" node)
EDGE_LOADS = [
    (queries.LINK_CLAIMANT_FILED_CLAIM, "claims", "claimant_id", "claim_id"),
    (queries.LINK_CLAIM_UNDER_POLICY, "claims", "claim_id", "policy_id"),
    (queries.LINK_CLAIM_INVOLVES_VEHICLE, "claims", "claim_id", "vehicle_id"),
    (queries.LINK_CLAIMANT_LIVES_AT_ADDRESS, "claimants", "claimant_id", "address_id"),
    (queries.LINK_CLAIMANT_HAS_PHONE, "claimants", "claimant_id", "phone_number"),
    (queries.LINK_CLAIM_REPAIRED_AT_PROVIDER, "claims", "claim_id", "repair_shop_id"),
    (queries.LINK_CLAIM_TREATED_BY_PROVIDER, "claims", "claim_id", "clinic_id"),
    (queries.LINK_CLAIM_REPRESENTED_BY_ATTORNEY, "claims", "claim_id", "attorney_id"),
    (
        queries.LINK_ATTORNEY_WORKS_AT_LAW_FIRM,
        "attorneys",
        "attorney_id",
        "law_firm_id",
    ),
    (queries.LINK_CLAIM_LED_TO_LAWSUIT, "lawsuits", "claim_id", "lawsuit_id"),
    (queries.LINK_LAWSUIT_FILED_IN_COURT, "lawsuits", "lawsuit_id", "court_id"),
    (
        queries.LINK_LAWSUIT_PLAINTIFF_COUNSEL,
        "lawsuits",
        "lawsuit_id",
        "plaintiff_law_firm_id",
    ),
    (queries.LINK_LAWSUIT_USES_EXPERT, "lawsuits", "lawsuit_id", "expert_id"),
    (queries.LINK_CLAIM_HAS_PAYMENT, "payments", "claim_id", "payment_id"),
    (queries.LINK_CLAIM_ARISES_FROM_INCIDENT, "claims", "claim_id", "incident_id"),
    (queries.LINK_CLAIM_HAS_TREATMENT, "treatments", "claim_id", "treatment_id"),
    (queries.LINK_TREATMENT_BY_PROVIDER, "treatments", "treatment_id", "provider_id"),
    (queries.LINK_CLAIM_HAS_RESERVE_EVENT, "reserve_events", "claim_id", "event_id"),
]


def read_tables(tables_dir):
    """Return {table name: list of rows}. Each row is a dict of text values, as in the CSV file."""
    tables = {}
    for table_name in TABLE_NAMES:
        file_path = tables_dir / f"{table_name}.csv"
        if not file_path.exists():
            raise FileNotFoundError(
                f"{file_path} is missing. The data generator makes the CSV tables."
            )
        with open(file_path, newline="", encoding="utf-8") as csv_file:
            tables[table_name] = list(csv.DictReader(csv_file))
    return tables


def make_id_pairs(rows, from_column, to_column):
    """Turn rows into [{from_id, to_id}, ...]. An empty ID (for example, a claim with no attorney) means no edge."""
    pairs = []
    for row in rows:
        if row[from_column] != "" and row[to_column] != "":
            pairs.append({"from_id": row[from_column], "to_id": row[to_column]})
    return pairs


def count_graph(driver):
    """Return ({label: number of nodes}, {edge type: number of edges}) as they are in Neo4j now."""
    node_counts = {}
    records, _, _ = driver.execute_query(queries.COUNT_NODES_BY_LABEL)
    for record in records:
        node_counts[record["label"]] = record["count"]
    edge_counts = {}
    records, _, _ = driver.execute_query(queries.COUNT_EDGES_BY_TYPE)
    for record in records:
        edge_counts[record["edge_type"]] = record["count"]
    return node_counts, edge_counts


def load_tables_into_graph(driver: Driver, tables_dir=config.TABLES_DIR):
    """Load all tables into Neo4j. Return (node counts, edge counts) after the load."""
    tables = read_tables(tables_dir)
    create_graph_schema(driver)
    for query, table_name in NODE_LOADS:
        driver.execute_query(query, rows=tables[table_name])
    for query, table_name, from_column, to_column in EDGE_LOADS:
        pairs = make_id_pairs(tables[table_name], from_column, to_column)
        driver.execute_query(query, pairs=pairs)
    return count_graph(driver)


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file", or:  .venv/bin/python -m src.data_loading.load_tables_into_graph
# This only READS the CSV files and shows the plan. It needs no Neo4j and writes nothing.
if __name__ == "__main__":
    tables = read_tables(config.TABLES_DIR)
    print("1. Rows in each table:", {name: len(rows) for name, rows in tables.items()})
    print("2. Node loads, in order:")
    for query, table_name in NODE_LOADS:
        print(f"   {len(tables[table_name]):>5} rows of {table_name}")
    print(
        "3. Edge loads: the number of edges that the rows make (empty IDs make none):"
    )
    for query, table_name, from_column, to_column in EDGE_LOADS:
        pairs = make_id_pairs(tables[table_name], from_column, to_column)
        print(
            f"   {len(pairs):>5} edges from {table_name}.{from_column} to {to_column}"
        )
    print(
        "4. Example: the first pair of claims -> policies:",
        make_id_pairs(tables["claims"], "claim_id", "policy_id")[0],
    )
