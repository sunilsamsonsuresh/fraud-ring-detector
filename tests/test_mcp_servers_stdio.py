"""Tests of the three MCP servers in src/mcp_servers/ (new system).

Each test starts a server as a separate program and talks to it over stdio, like a real client.
The tools are the real plain code on the real Neo4j data. No test calls an LLM.
The expected values come from the CSV files or from the plain tools, not from the server itself.
"""

import csv
import json

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.mcp_servers.call_server_tool import use_server
from src.tools.claim_tools import get_claim_record
from src.tools.link_tools import get_claim_neighbourhood
from src.tools.score_tools import get_claim_score
from src.tools.search_tools import (
    claims_linked_to_name,
    claims_with_phone,
    search_all_documents,
    search_claim_documents,
)

RECORDS = "src.mcp_servers.claim_records_server"
LINKS = "src.mcp_servers.graph_links_server"
DOCUMENTS = "src.mcp_servers.document_search_server"
QUERY = "src.mcp_servers.query_server"
RING_B_CLAIM = "C-1088"
LINKED_CLAIM = "C-1026"  # shares a phone and an address with other claims
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


def as_plain_json(answer):
    """What a client receives: the answer after it went through JSON."""
    return json.loads(json.dumps(answer, default=str))


def test_each_server_lists_exactly_its_tools_and_they_only_read():
    expected = {
        RECORDS: ["get_claim_record", "get_claim_score", "list_claims_by_score"],
        LINKS: [
            "find_claims_linked_to_name",
            "find_claims_sharing_phone",
            "find_shared_groups",
            "get_claim_neighbourhood",
            "get_community",
            "get_entity_context",
            "list_communities",
        ],
        DOCUMENTS: [
            "get_claim_findings",
            "search_all_documents",
            "search_claim_documents",
        ],
        QUERY: ["get_graph_map", "run_read_query"],
    }
    for server_module, tool_names in expected.items():
        tools, _ = use_server(server_module, [])
        assert sorted(tool.name for tool in tools) == tool_names
        for tool in tools:
            assert tool.annotations.readOnlyHint is True, tool.name
            assert tool.description, tool.name


def test_the_claim_record_over_mcp_matches_the_csv_files():
    _, (result,) = use_server(
        RECORDS, [("get_claim_record", {"claim_id": RING_B_CLAIM})]
    )
    assert not result.isError
    facts = result.structuredContent["facts"]
    with open(config.TABLES_DIR / "treatments.csv", encoding="utf-8") as file:
        visit_dates = sorted(
            row["visit_date"]
            for row in csv.DictReader(file)
            if row["claim_id"] == RING_B_CLAIM
        )
    with open(config.TABLES_DIR / "payments.csv", encoding="utf-8") as file:
        payments = [
            float(row["amount"])
            for row in csv.DictReader(file)
            if row["claim_id"] == RING_B_CLAIM
        ]
    assert facts["treatment"]["visit_count"] == len(visit_dates)
    assert facts["treatment"]["first_visit_date"] == visit_dates[0]
    assert facts["payments"]["total_paid"] == round(sum(payments), 2)
    assert result.structuredContent["sources"]


def test_the_score_over_mcp_equals_the_plain_tool(driver):
    _, (result,) = use_server(
        RECORDS, [("get_claim_score", {"claim_id": RING_B_CLAIM})]
    )
    plain = as_plain_json(get_claim_score(driver, RING_B_CLAIM))
    assert not result.isError
    assert result.structuredContent == plain
    assert plain["facts"]["total_score"] == 22.2 and plain["facts"]["band"] == "High"


def test_the_neighbourhood_over_mcp_equals_the_plain_tool(driver):
    _, (result,) = use_server(
        LINKS, [("get_claim_neighbourhood", {"claim_id": LINKED_CLAIM})]
    )
    assert result.structuredContent == as_plain_json(
        get_claim_neighbourhood(driver, LINKED_CLAIM)
    )
    linked = {
        row["claim_id"] for row in result.structuredContent["facts"]["linked_claims"]
    }
    assert {"C-1202", "C-1209"} <= linked  # the shared phone 713-555-2172


def test_phone_and_name_over_mcp_equal_the_plain_tools(driver):
    _, (by_phone, by_name) = use_server(
        LINKS,
        [
            ("find_claims_sharing_phone", {"phone": "(713) 555-2172"}),
            ("find_claims_linked_to_name", {"name": "Santiago & Romero Law Group"}),
        ],
    )
    assert by_phone.structuredContent == as_plain_json(
        claims_with_phone(driver, "713-555-2172")
    )
    assert by_name.structuredContent == as_plain_json(
        claims_linked_to_name(driver, "Santiago & Romero Law Group")
    )


def test_the_document_search_over_mcp_equals_the_plain_tool(driver):
    topic = "passenger was not in the car"
    _, (result,) = use_server(
        DOCUMENTS,
        [("search_claim_documents", {"claim_id": RING_B_CLAIM, "topic": topic})],
    )
    assert not result.isError
    plain = as_plain_json(search_claim_documents(driver, RING_B_CLAIM, topic))
    assert [p["source"] for p in result.structuredContent["facts"]["passages"]] == [
        p["source"] for p in plain["facts"]["passages"]
    ]
    assert result.structuredContent["sources"]


def test_the_hybrid_search_over_mcp_equals_the_plain_tool(driver):
    topic = "home stretching instructions"
    _, (result,) = use_server(DOCUMENTS, [("search_all_documents", {"topic": topic})])
    assert not result.isError
    plain = as_plain_json(search_all_documents(driver, topic))
    assert result.structuredContent == plain
    _, (empty,) = use_server(DOCUMENTS, [("search_all_documents", {"topic": "  "})])
    assert "topic is empty" in empty.structuredContent["message"]


def test_a_generated_query_over_mcp_is_checked_and_read_only(driver):
    before = count_graph(driver)
    _, results = use_server(
        QUERY,
        [
            ("run_read_query", {"query": "MATCH (c:Claim) RETURN count(c) AS claims"}),
            ("run_read_query", {"query": ATTACK}),
            ("get_graph_map", {}),
        ],
    )
    assert results[0].structuredContent["facts"]["rows"] == [{"claims": 500}]
    assert "refused" in results[1].structuredContent["message"]
    assert results[1].structuredContent["sources"] == []
    assert results[2].structuredContent["facts"]["nodes"]
    assert count_graph(driver) == before


def test_the_communities_over_mcp_equal_the_plain_tools(driver):
    from src.tools.community_tools import get_community, list_communities

    _, results = use_server(
        LINKS,
        [
            ("list_communities", {}),
            ("get_community", {"community_or_claim_id": " c-1088 "}),
            ("get_community", {"community_or_claim_id": ATTACK}),
        ],
    )
    assert results[0].structuredContent == as_plain_json(list_communities(driver))
    assert results[1].structuredContent == as_plain_json(
        get_community(driver, ("claim", RING_B_CLAIM))
    )
    assert "not a community ID" in results[2].structuredContent["message"]


def test_bad_values_give_messages_and_the_graph_does_not_change(driver):
    before = count_graph(driver)
    _, results = use_server(
        RECORDS,
        [
            ("get_claim_record", {"claim_id": ATTACK}),
            ("get_claim_score", {"claim_id": "C-9999"}),
        ],
    )
    assert "not a claim ID" in results[0].structuredContent["message"]
    assert (
        results[1].structuredContent["message"]
        == "Claim C-9999 was not found in the graph."
    )

    _, results = use_server(
        LINKS,
        [
            ("get_claim_neighbourhood", {"claim_id": "c-12"}),
            ("find_claims_sharing_phone", {"phone": ATTACK}),
            ("find_claims_linked_to_name", {"name": "ab"}),
        ],
    )
    assert "not a claim ID" in results[0].structuredContent["message"]
    assert "not a phone number" in results[1].structuredContent["message"]
    assert "too short" in results[2].structuredContent["message"]

    _, results = use_server(
        DOCUMENTS,
        [
            ("search_claim_documents", {"claim_id": RING_B_CLAIM, "topic": "  "}),
            ("search_claim_documents", {"claim_id": ATTACK, "topic": "x"}),
        ],
    )
    assert "topic is empty" in results[0].structuredContent["message"]
    assert "not a claim ID" in results[1].structuredContent["message"]
    for result in results:
        assert result.structuredContent["sources"] == []
    assert count_graph(driver) == before


def test_a_claim_id_with_spaces_and_small_letters_is_cleaned():
    _, (result,) = use_server(RECORDS, [("get_claim_record", {"claim_id": " c-1088 "})])
    assert result.structuredContent["facts"]["claim_id"] == RING_B_CLAIM


def test_neo4j_down_gives_a_message_and_not_a_crash(monkeypatch):
    from src.mcp_servers import server_helpers

    def neo4j_is_down():
        raise RuntimeError(
            "Cannot reach Neo4j at bolt://localhost:7687. Is it running?"
        )

    monkeypatch.setattr(server_helpers, "open_neo4j_driver", neo4j_is_down)
    answer = server_helpers.run_tool_for_claim("C-1088", get_claim_record)
    assert answer == {
        "message": "Cannot reach Neo4j at bolt://localhost:7687. Is it running?",
        "sources": [],
    }
