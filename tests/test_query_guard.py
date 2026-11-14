"""Tests of the graph query parts (build step 4): src/tools/query_guard.py, src/tools/query_tools.py and
src/data_loading/write_graph_map.py. They run on the real graph (Neo4j must be running). No LLM is called.

The expected numbers come from the CSV files in data/tables/, not from the queries under test.
"""

import csv
import json

import pytest

from src import config
from src.data_loading.write_graph_map import write_graph_map
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.tools.query_guard import check_generated_query
from src.tools.query_tools import get_graph_map, run_read_query

ATTACK = "MATCH (n) DETACH DELETE n"


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def count_graph(driver):
    records, _, _ = driver.execute_query(
        "MATCH (n) RETURN count(n) AS nodes, COUNT { ()-->() } AS links"
    )
    return records[0]["nodes"], records[0]["links"]


def read_csv(file_name):
    with open(config.TABLES_DIR / file_name, encoding="utf-8") as file:
        return list(csv.DictReader(file))


# --- Check 1: the text (no Neo4j needed) ---


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (c:Claim) RETURN count(c) AS n",
        "match (c:Claim) where c.settlement_amount > 0 return c.claim_id limit 5",
        "MATCH (c:Claim) RETURN c.claim_id LIMIT 3;",
        "OPTIONAL MATCH (c:Claim) RETURN c.claim_id LIMIT 1",
        "CALL db.index.fulltext.queryNodes('chunk_text_index', 'neck') YIELD node RETURN node.chunk_id LIMIT 3",
    ],
)
def test_a_read_query_passes(query):
    checked, problem = check_generated_query(query)
    assert problem is None and checked == query.strip().rstrip(";").strip()


@pytest.mark.parametrize(
    "query, reason",
    [
        ("", "empty"),
        (ATTACK, "DELETE"),
        ("MATCH (c:Claim) SET c.flag = true RETURN c", "SET"),
        ("CREATE (x:Claim {claim_id: 'C-0000'})", "must start with"),
        ("MATCH (c:Claim) MERGE (c)-[:X]->(c) RETURN c", "MERGE"),
        ("MATCH (c:Claim) RETURN c; MATCH (n) DELETE n", "one query only"),
        ("LOAD CSV FROM 'file:///x' AS row RETURN row", "must start with"),
        ("MATCH (c) FOREACH (x IN [1] | REMOVE c.claim_id) RETURN c", "not allowed"),
        ("CALL dbms.components() YIELD name RETURN name", "not allowed"),
        ("CALL apoc.cypher.runWrite('x', {}) YIELD value RETURN value", "not allowed"),
        ("CALL { MATCH (c:Claim) RETURN c } RETURN count(c)", "subqueries"),
        ("MATCH (c:Claim) RETURN c" + " " * 10 + "x" * 2000, "longer than"),
    ],
)
def test_a_write_or_unknown_call_is_refused_with_a_reason(query, reason):
    checked, problem = check_generated_query(query)
    assert checked is None and reason in problem


# --- Checks 2 and 3, and the run (real graph) ---


def test_counts_are_exact(driver):
    answer = run_read_query(driver, "MATCH (c:Claim) RETURN count(c) AS claims")
    assert answer["facts"]["rows"] == [{"claims": len(read_csv("claims.csv"))}]
    assert answer["sources"] == [
        "Read-only graph query: MATCH (c:Claim) RETURN count(c) AS claims"
    ]


def test_the_newest_band_counts_equal_the_fixed_query(driver):
    records, _, _ = driver.execute_query(queries.LATEST_SCORE_OF_EVERY_CLAIM)
    expected = {}
    for record in records:
        expected[record["band"]] = expected.get(record["band"], 0) + 1
    answer = run_read_query(
        driver,
        "MATCH (c:Claim)-[:HAS_SCORE]->(s:ScoreSnapshot) WITH c, s ORDER BY s.as_of_date DESC "
        "WITH c, head(collect(s)) AS latest RETURN latest.band AS band, count(*) AS claims LIMIT 10",
    )
    got = {row["band"]: row["claims"] for row in answer["facts"]["rows"]}
    expected.pop(None, None)  # a claim with no snapshot has no band
    assert got == expected


def test_the_row_limit_cuts_and_says_so(driver):
    answer = run_read_query(
        driver, "MATCH (c:Claim) RETURN c.claim_id AS id ORDER BY id"
    )
    assert answer["facts"]["row_count"] == config.GENERATED_QUERY_MAX_ROWS
    assert any("Only the first" in note for note in answer["notes"])


def test_a_whole_node_comes_back_without_its_embedding(driver):
    answer = run_read_query(driver, "MATCH (c:Chunk) RETURN c LIMIT 1")
    chunk = answer["facts"]["rows"][0]["c"]
    assert "text" in chunk and "embedding" not in chunk


def test_a_syntax_error_comes_back_as_a_reason(driver):
    answer = run_read_query(driver, "MATCH (c:Claim RETURN c")
    assert "Neo4j cannot run this query" in answer["message"]


def test_a_slow_query_is_stopped(driver, monkeypatch):
    monkeypatch.setattr(config, "GENERATED_QUERY_SECONDS", 1)
    answer = run_read_query(
        driver,
        "UNWIND range(1, 300000000) AS x WITH x WHERE x % 7 = 0 RETURN count(x) AS n",
    )
    assert "The query failed" in answer["message"]


def test_refused_queries_change_nothing(driver):
    before = count_graph(driver)
    for query in [ATTACK, "MATCH (c:Claim) SET c.x = 1", "CALL { CREATE (x) }"]:
        assert "refused" in run_read_query(driver, query)["message"]
    assert count_graph(driver) == before


def test_a_write_hidden_from_the_text_check_is_still_refused_by_neo4j(
    driver, monkeypatch
):
    # Pretend check 1 lets everything pass. EXPLAIN (check 2) must still refuse the write.
    from src.tools import query_tools

    monkeypatch.setattr(query_tools, "check_generated_query", lambda text: (text, None))
    before = count_graph(driver)
    answer = query_tools.run_read_query(driver, "CREATE (x:GuardTest) RETURN x")
    assert "not read-only" in answer["message"]
    assert count_graph(driver) == before


# --- The graph map ---


def test_the_graph_map_matches_the_graph(driver, tmp_path):
    graph_map = write_graph_map(driver, tmp_path / "graph_map.json")
    with open(tmp_path / "graph_map.json", encoding="utf-8") as file:
        assert json.load(file) == graph_map
    nodes = {node["label"]: node for node in graph_map["nodes"]}
    assert nodes["Claim"]["count"] == len(read_csv("claims.csv"))
    assert "claim_id" in nodes["Claim"]["properties"]
    assert "embedding" not in nodes["Chunk"]["properties"]
    patterns = {
        (r["from_label"], r["type"], r["to_label"]) for r in graph_map["relationships"]
    }
    assert ("Claimant", "FILED", "Claim") in patterns
    assert "High" in graph_map["field_values"]["ScoreSnapshot.band"]
    assert graph_map["notes"]


def test_a_missing_graph_map_gives_a_message(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GRAPH_MAP_FILE", tmp_path / "missing.json")
    assert "graph map is missing" in get_graph_map()["message"]
