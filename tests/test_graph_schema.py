"""Tests of src/data_loading/graph_schema.py (new system). They run on the real graph (Neo4j must be running).

The graph already has its schema, so these tests check three things: the statements are written
correctly, they equal the old schema, and running them again changes nothing.
"""

import re

import pytest

from src import config
from src.data_loading import graph_schema
from src.graph.connection import open_neo4j_driver

ALL_STATEMENTS = (
    graph_schema.UNIQUE_ID_CONSTRAINTS
    + graph_schema.LOOKUP_INDEXES
    + [graph_schema.CHUNK_VECTOR_INDEX, graph_schema.CHUNK_TEXT_INDEX]
)


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def names_in_graph(driver, show_command):
    records, _, _ = driver.execute_query(show_command)
    return {record["name"] for record in records}


def test_every_statement_is_safe_to_run_twice():
    for statement in ALL_STATEMENTS:
        assert "IF NOT EXISTS" in statement, statement


def test_every_node_label_of_the_scoring_has_an_id_constraint():
    labels = set()
    for statement in graph_schema.UNIQUE_ID_CONSTRAINTS:
        labels.add(re.search(r"\(n:(\w+)\)", statement).group(1))
    assert labels == {
        "Claim",
        "Claimant",
        "Incident",
        "Policy",
        "Vehicle",
        "Address",
        "Phone",
        "Provider",
        "Attorney",
        "LawFirm",
        "Lawsuit",
        "Court",
        "Expert",
        "Payment",
        "Treatment",
        "ReserveEvent",
        "Document",
        "Chunk",
        "Finding",
        "ScoreSnapshot",
    }


def test_the_vector_index_size_equals_the_config():
    assert (
        f"`vector.dimensions`: {config.EMBEDDING_DIMENSIONS},"
        in graph_schema.CHUNK_VECTOR_INDEX
    )


def test_the_text_index_name_equals_the_config():
    assert f"INDEX {config.CHUNK_TEXT_INDEX_NAME} IF NOT EXISTS" in (
        graph_schema.CHUNK_TEXT_INDEX
    )


def test_the_names_in_the_statements_exist_in_the_graph(driver):
    expected = set()
    for statement in ALL_STATEMENTS:
        expected.add(
            re.match(
                r"CREATE (?:VECTOR |FULLTEXT )?(?:CONSTRAINT|INDEX) (\w+)", statement
            ).group(1)
        )
    in_graph = names_in_graph(
        driver, "SHOW CONSTRAINTS YIELD name RETURN name"
    ) | names_in_graph(driver, "SHOW INDEXES YIELD name RETURN name")
    assert expected <= in_graph


def test_running_the_schema_again_changes_nothing(driver):
    nodes_before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS n")
    constraints_before = names_in_graph(
        driver, "SHOW CONSTRAINTS YIELD name RETURN name"
    )
    indexes_before = names_in_graph(driver, "SHOW INDEXES YIELD name RETURN name")
    graph_schema.create_graph_schema(driver)
    nodes_after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS n")
    assert nodes_after[0]["n"] == nodes_before[0]["n"]
    assert (
        names_in_graph(driver, "SHOW CONSTRAINTS YIELD name RETURN name")
        == constraints_before
    )
    assert (
        names_in_graph(driver, "SHOW INDEXES YIELD name RETURN name") == indexes_before
    )
