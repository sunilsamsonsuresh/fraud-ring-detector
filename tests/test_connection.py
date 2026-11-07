"""Step 0 test: Python can connect to Neo4j and run a query.

Neo4j must be running (docker compose up -d) and .env must exist.
"""

from src.graph.connection import open_neo4j_driver


def test_neo4j_returns_one():
    driver = open_neo4j_driver()
    try:
        records, summary, keys = driver.execute_query("RETURN 1 AS number")
    finally:
        driver.close()

    assert records[0]["number"] == 1
