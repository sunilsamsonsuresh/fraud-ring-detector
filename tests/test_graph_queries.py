"""Tests of src/graph/queries.py (new system). They run on the real graph (Neo4j must be running).

The expected values come from the CSV files in data/tables/, the source of the graph, and not from the queries.
"""

import csv

import pytest

from src import config
from src.graph import queries
from src.graph.connection import open_neo4j_driver

CLAIM_ID = "C-1088"
ATTACK = "MATCH (n) DETACH DELETE n"


def read_csv(file_name):
    with open(config.TABLES_DIR / file_name, encoding="utf-8") as file:
        return list(csv.DictReader(file))


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


NO_VALUE_QUERIES = [
    "LATEST_SCORE_OF_EVERY_CLAIM",
    "ALL_CLAIM_IDS",
    "GRAPH_MAP_LABELS",
    "GRAPH_MAP_RELATIONSHIPS",
]  # they take no value at all (see the tests at the end)
# They take a value that is not a claim: a label or a type from a fixed list (graph map), a limit, or a
# community ID that was checked before (src/tools/checks.py). Tests at the end.
OTHER_VALUE_QUERIES = [
    "GRAPH_MAP_NODE_PROPERTIES",
    "GRAPH_MAP_RELATIONSHIP_PROPERTIES",
    "GRAPH_MAP_VALUES",
    "LIST_COMMUNITIES",
    "COMMUNITY_BY_ID",
]
# The hybrid search queries take an embedding, words or chunk IDs, not a claim ID (tests at the end).
HYBRID_SEARCH_QUERIES = [
    "SEARCH_CHUNKS_BY_MEANING",
    "SEARCH_CHUNKS_BY_WORDS",
    "EXPAND_CHUNKS",
]


def all_queries():
    """Queries that take a value from the caller. The GROUPS_ queries take no value, only fixed numbers (see below)."""
    return {
        name: value
        for name, value in vars(queries).items()
        if name.isupper()
        and name not in NO_VALUE_QUERIES
        and name not in HYBRID_SEARCH_QUERIES
        and name not in OTHER_VALUE_QUERIES
        and not name.startswith("GROUPS_")
    }


def group_queries():
    return {
        name: value
        for name, value in vars(queries).items()
        if name.startswith("GROUPS_")
    }


# Some queries take more parameters than the claim ID (the copied-story queries).
EXTRA_PARAMETERS = {
    "document_types": config.STORY_DOCUMENT_TYPES,
    "index_name": config.CHUNK_VECTOR_INDEX_NAME,
    "candidate_count": config.COPY_CANDIDATES,
    "min_score": config.SIMILARITY_THRESHOLD,
    "exact": True,
    "embedding": [1.0] + [0.0] * (config.EMBEDDING_DIMENSIONS - 1),
    "limit": 5,
    # The entity queries: a label and its ID key from the fixed list, and a list of claims.
    "kind": "Attorney",
    "id_property": "attorney_id",
    "claim_ids": [],
}
# The lookup queries take the tested value under another name (a phone or a name, not a claim ID).
VALUE_PARAMETERS = ["phone_end", "name", "entity_id"]


def run(driver, query, claim_id=CLAIM_ID):
    wanted = {
        name: value for name, value in EXTRA_PARAMETERS.items() if "$" + name in query
    }
    for name in VALUE_PARAMETERS:
        if "$" + name in query:
            wanted[name] = claim_id
    records, _, _ = driver.execute_query(query, claim_id=claim_id, **wanted)
    return [record.data() for record in records]


def test_every_query_takes_its_value_as_a_parameter():
    for name, text in all_queries().items():
        assert "$claim_id" in text or any(
            "$" + value_name in text for value_name in VALUE_PARAMETERS
        ), name


def test_claim_exists_finds_a_claim_and_not_a_missing_one(driver):
    assert run(driver, queries.CLAIM_EXISTS) == [{"claim_id": CLAIM_ID}]
    assert run(driver, queries.CLAIM_EXISTS, claim_id="C-9999") == []


def test_query_text_as_a_value_matches_nothing_and_changes_nothing(driver):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    for query in all_queries().values():
        assert run(driver, query, claim_id=ATTACK) == []
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert after[0]["nodes"] == before[0]["nodes"]


def test_claim_and_policy_match_the_csv_files(driver):
    expected = next(
        row for row in read_csv("claims.csv") if row["claim_id"] == CLAIM_ID
    )
    rows = run(driver, queries.CLAIM_AND_POLICY)
    assert len(rows) == 1
    row = rows[0]
    assert str(row["loss_date"]) == expected["loss_date"]
    assert str(row["reported_date"]) == expected["reported_date"]
    assert str(row["attorney_retained_date"]) == expected["attorney_retained_date"]
    assert row["repair_estimate_amount"] == float(expected["repair_estimate_amount"])
    assert row["incident_id"] == expected["incident_id"]
    assert row["policy_id"] == expected["policy_id"]


def test_visits_match_the_csv_file_in_date_order(driver):
    expected = sorted(
        row["visit_date"]
        for row in read_csv("treatments.csv")
        if row["claim_id"] == CLAIM_ID
    )
    assert [
        str(row["visit_date"]) for row in run(driver, queries.CLAIM_VISIT_DATES)
    ] == expected


def test_payments_match_the_csv_file(driver):
    expected = sorted(
        row["payment_id"]
        for row in read_csv("payments.csv")
        if row["claim_id"] == CLAIM_ID
    )
    rows = run(driver, queries.CLAIM_PAYMENTS)
    assert sorted(row["payment_id"] for row in rows) == expected
    assert [row["payment_date"] for row in rows] == sorted(
        row["payment_date"] for row in rows
    )


def test_reserve_events_match_the_csv_file(driver):
    expected = sorted(
        row["event_id"]
        for row in read_csv("reserve_events.csv")
        if row["claim_id"] == CLAIM_ID
    )
    rows = run(driver, queries.CLAIM_RESERVE_EVENTS)
    assert sorted(row["event_id"] for row in rows) == expected


def test_lawsuits_match_the_csv_file(driver):
    lawsuit = read_csv("lawsuits.csv")[0]  # a claim that has a lawsuit
    rows = run(driver, queries.CLAIM_LAWSUITS, claim_id=lawsuit["claim_id"])
    assert [row["lawsuit_id"] for row in rows] == [lawsuit["lawsuit_id"]]
    assert str(rows[0]["filed_date"]) == lawsuit["filed_date"]
    assert run(driver, queries.CLAIM_LAWSUITS) == []  # C-1088 has no lawsuit


# --- The group queries (questions with no claim ID) ---


def test_group_queries_take_only_fixed_numbers_as_parameters():
    for name, text in group_queries().items():
        parameters = {
            word.strip(",)[]")
            for word in text.replace("[", " ").split()
            if word.startswith("$")
        }
        assert parameters <= {"$min_claims", "$limit"}, name


def test_the_address_groups_match_the_csv_files(driver):
    claims = {row["claim_id"]: row for row in read_csv("claims.csv")}
    claimants = {row["claimant_id"]: row for row in read_csv("claimants.csv")}
    addresses = {}
    for claim in claims.values():
        address_id = claimants[claim["claimant_id"]]["address_id"]
        addresses.setdefault(address_id, []).append(claim)
    expected = []
    for address_claims in addresses.values():
        claimant_count = len({claim["claimant_id"] for claim in address_claims})
        incident_count = len({claim["incident_id"] for claim in address_claims})
        if claimant_count >= 2 and incident_count >= 2:
            expected.append(sorted(claim["claim_id"] for claim in address_claims))

    records, _, _ = driver.execute_query(
        queries.GROUPS_SHARED_ADDRESS, min_claims=2, limit=1000
    )
    found = [sorted(group["claim_ids"]) for group in records[0]["groups"]]
    assert records[0]["group_count"] == len(expected) == len(found)
    assert sorted(found) == sorted(expected)


def test_the_groups_come_biggest_first_and_the_limit_cuts_the_list(driver):
    for name, text in group_queries().items():
        records, _, _ = driver.execute_query(text, min_claims=2, limit=2)
        sizes = [group["claim_count"] for group in records[0]["groups"]]
        assert len(sizes) <= 2 and sizes == sorted(sizes, reverse=True), name


def test_a_group_never_comes_from_one_incident(driver):
    claim_incident = {
        row["claim_id"]: row["incident_id"] for row in read_csv("claims.csv")
    }
    for name, text in group_queries().items():
        records, _, _ = driver.execute_query(text, min_claims=2, limit=1000)
        for group in records[0]["groups"]:
            assert (
                len({claim_incident[claim_id] for claim_id in group["claim_ids"]}) >= 2
            ), (name, group["shared_value"])


def test_group_queries_do_not_change_the_graph(driver):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    for text in group_queries().values():
        driver.execute_query(text, min_claims=2, limit=5)
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert after[0]["nodes"] == before[0]["nodes"]


def test_the_saved_score_query_takes_no_parameter_and_gives_one_row_per_claim(driver):
    assert "$" not in queries.LATEST_SCORE_OF_EVERY_CLAIM
    records, _, _ = driver.execute_query(queries.LATEST_SCORE_OF_EVERY_CLAIM)
    rows = [record.data() for record in records]
    assert [row["claim_id"] for row in rows] == sorted(
        claim["claim_id"] for claim in read_csv("claims.csv")
    )
    assert all(row["total_score"] is not None and row["band"] for row in rows)


def test_the_saved_score_query_takes_the_newest_snapshot(driver):
    newest, _, _ = driver.execute_query(
        "MATCH (:Claim {claim_id: $claim_id})-[:HAS_SCORE]->(s:ScoreSnapshot) RETURN toString(max(s.as_of_date)) AS day",
        claim_id=CLAIM_ID,
    )
    records, _, _ = driver.execute_query(queries.LATEST_SCORE_OF_EVERY_CLAIM)
    row = next(record.data() for record in records if record["claim_id"] == CLAIM_ID)
    assert row["as_of_date"] == newest[0]["day"]


def test_the_hybrid_search_queries_take_their_values_as_parameters(driver):
    assert "$embedding" in queries.SEARCH_CHUNKS_BY_MEANING
    assert "$words" in queries.SEARCH_CHUNKS_BY_WORDS
    assert "$chunk_ids" in queries.EXPAND_CHUNKS
    records, _, _ = driver.execute_query(queries.EXPAND_CHUNKS, chunk_ids=[ATTACK])
    assert records == []


def test_queries_py_holds_no_write_query():
    # The pipeline keeps its write queries next to its code. Every query here only reads.
    for name, text in vars(queries).items():
        if name.isupper() and isinstance(text, str):
            for word in ["CREATE", "MERGE", "SET ", "DELETE", "REMOVE"]:
                assert word not in text, (name, word)


def test_the_other_value_queries_match_nothing_for_attack_text(driver):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert driver.execute_query(queries.COMMUNITY_BY_ID, community_id=ATTACK)[0] == []
    rows, _, _ = driver.execute_query(
        queries.GRAPH_MAP_VALUES, label=ATTACK, property=ATTACK
    )
    assert rows == []
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert after[0]["nodes"] == before[0]["nodes"]
