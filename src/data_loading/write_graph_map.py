"""Pipeline step 5 (the last part): write the graph map, the file that tells the graph query agent what is in the graph.

The graph query agent writes its own read-only queries (text-to-Cypher). To write a correct query, it must
know the node labels, their properties, the relationships between them, and the values of a few fields
(for example the bands "High" and "Low"). This file reads all of that from the LIVE graph, so the map
never gets out of date, and adds a few notes that a person wrote.

Run it after the graph is loaded:  .venv/bin/python -m src.data_loading.write_graph_map
It only reads the graph. It writes one file: data/graph_map.json (config.GRAPH_MAP_FILE). No LLM is called.
"""

import json

from src import config
from src.graph import queries

# A property we never show: one embedding is 384 numbers, and nobody queries it by hand.
HIDDEN_PROPERTIES = ["embedding"]

# Fields with a few fixed values. The map lists their values, so the agent writes "High" and not "high".
FIELDS_WITH_VALUES = [
    ("ScoreSnapshot", "band"),
    ("Claim", "status"),
    ("Claim", "injury_type"),
    ("Claim", "accident_type"),
    ("Document", "document_type"),
    ("Finding", "feature"),
    ("Finding", "confidence"),
    ("Provider", "type"),
]

# What a person must know to read the graph correctly. The agent reads these notes with the map.
NOTES = [
    "Each claim has one Claimant: (:Claimant)-[:FILED]->(:Claim).",
    (
        "A claim has many ScoreSnapshot nodes (its score over time). The current score is the snapshot "
        "with the biggest as_of_date."
    ),
    (
        "Claims of the SAME Incident ((:Claim)-[:ARISES_FROM]->(:Incident)) are one accident. A link between "
        "them is not network evidence. Leave such pairs out when you look for links between claims."
    ),
    "Dates are Neo4j date values. Compare them with date('2024-01-31').",
    (
        "Finding: value is the rating, confidence is Low, Medium or High, quote is the exact text, and "
        "page_number with (:Finding)-[:FOUND_IN]->(:Document) gives the source."
    ),
    "Community: a group of claims joined by strong links: (:Claim)-[:IN_COMMUNITY]->(:Community).",
    "Return plain values (claim_id, names, counts), never whole nodes. Always end with LIMIT.",
]


def values_from(driver, query, column, **parameters):
    records, _, _ = driver.execute_query(query, **parameters)
    return [record[column] for record in records]


def build_graph_map(driver):
    """The map as a dict: nodes (label, count, properties), relationships, field values and notes."""
    nodes = []
    records, _, _ = driver.execute_query(queries.GRAPH_MAP_LABELS)
    for record in records:
        properties = []
        for name in values_from(
            driver,
            queries.GRAPH_MAP_NODE_PROPERTIES,
            "property",
            label=record["label"],
        ):
            if name not in HIDDEN_PROPERTIES:
                properties.append(name)
        nodes.append(
            {
                "label": record["label"],
                "count": record["count"],
                "properties": properties,
            }
        )

    relationships = []
    records, _, _ = driver.execute_query(queries.GRAPH_MAP_RELATIONSHIPS)
    for record in records:
        relationship = record.data()
        relationship["properties"] = values_from(
            driver,
            queries.GRAPH_MAP_RELATIONSHIP_PROPERTIES,
            "property",
            type=record["type"],
        )
        relationships.append(relationship)

    field_values = {}
    for label, property_name in FIELDS_WITH_VALUES:
        values = values_from(
            driver,
            queries.GRAPH_MAP_VALUES,
            "value",
            label=label,
            property=property_name,
        )
        if values:
            field_values[f"{label}.{property_name}"] = values

    return {
        "nodes": nodes,
        "relationships": relationships,
        "field_values": field_values,
        "notes": NOTES,
    }


def write_graph_map(driver, map_file=config.GRAPH_MAP_FILE):
    """Build the map and save it as JSON. Return the map."""
    graph_map = build_graph_map(driver)
    with open(map_file, "w", encoding="utf-8") as file:
        json.dump(graph_map, file, indent=1)
    return graph_map


if __name__ == "__main__":
    from src.graph.connection import open_neo4j_driver

    graph_driver = open_neo4j_driver()
    try:
        written = write_graph_map(graph_driver)
    finally:
        graph_driver.close()
    print(
        f"Wrote {config.GRAPH_MAP_FILE}: {len(written['nodes'])} node labels, "
        f"{len(written['relationships'])} relationship patterns."
    )
