"""Plain-code tools of the graph query agent: read the graph map, and run ONE generated read-only query.

get_graph_map:   what is in the graph (labels, properties, relationships, field values, notes).
run_read_query:  check a generated query (src/tools/query_guard.py), then run it in a READ session with a
                 time limit and a row limit. Neo4j refuses any write in a READ session.

The result has the same two shapes as the other tools: {"facts", "notes", "sources"} or {"message"}.
No LLM is called here.
"""

import json

import neo4j
from neo4j.exceptions import Neo4jError
from neo4j.graph import Node, Relationship

from src import config
from src.tools.query_guard import check_generated_query, check_plan_is_read_only
from src.tools.score_tools import make_json_safe

HIDDEN_PROPERTIES = ["embedding"]  # 384 numbers: useless in an answer and very long


def get_graph_map():
    """The graph map written by the pipeline (src/data_loading/write_graph_map.py)."""
    if not config.GRAPH_MAP_FILE.exists():
        return {
            "message": "The graph map is missing. Run: python -m src.data_loading.write_graph_map"
        }
    with open(config.GRAPH_MAP_FILE, encoding="utf-8") as file:
        graph_map = json.load(file)
    return {
        "facts": graph_map,
        "notes": ["Write ONE read-only Cypher query with these labels and properties."],
        "sources": ["Graph map (data/graph_map.json)"],
    }


def plain_value(value):
    """A value from Neo4j as plain data. A whole node becomes its properties (without the embedding)."""
    if isinstance(value, Node):
        properties = {}
        for name, property_value in value.items():
            if name not in HIDDEN_PROPERTIES:
                properties[name] = property_value
        return properties
    if isinstance(value, Relationship):
        return {"relationship": value.type, **dict(value.items())}
    if isinstance(value, list):
        return [plain_value(item) for item in value]
    return value


def run_read_query(driver, query_text):
    """Check the generated query, then run it read-only. Return its rows (at most GENERATED_QUERY_MAX_ROWS)."""
    query, problem = check_generated_query(query_text)
    if problem is not None:
        return {"message": f"The query was refused: {problem}"}

    max_rows = config.GENERATED_QUERY_MAX_ROWS
    try:
        with driver.session(default_access_mode=neo4j.READ_ACCESS) as session:
            problem = check_plan_is_read_only(session, query)
            if problem is not None:
                return {"message": f"The query was refused: {problem}"}
            result = session.run(
                neo4j.Query(query, timeout=config.GENERATED_QUERY_SECONDS)
            )
            # fetch(n) reads at most n rows. One more than the limit tells us if rows were left out.
            records = result.fetch(max_rows + 1)
    except Neo4jError as error:
        # For example the time limit, or a value of the wrong type. The agent can fix the query.
        return {"message": f"The query failed: {str(error.message)[:300]}"}

    rows = []
    for record in records[:max_rows]:
        row = {}
        # items() gives (column name, value). A plain "for x in record" would give only the values.
        for key, value in record.items():
            row[key] = plain_value(value)
        rows.append(row)
    notes = ["The query only read the graph. The rows are exact counts and values."]
    if len(records) > max_rows:
        notes.append(
            f"More than {max_rows} rows matched. Only the first {max_rows} are shown."
        )
    if not rows:
        notes.append("The query found no rows.")
    one_line_query = " ".join(query.split())
    return {
        "facts": make_json_safe(
            {"query": one_line_query, "row_count": len(rows), "rows": rows}
        ),
        "notes": notes,
        "sources": [f"Read-only graph query: {one_line_query}"],
    }
