"""Tests that load data into an EMPTY scratch Neo4j, and compare the result with the live graph.

The live graph is only read. The scratch database is a second Neo4j that holds nothing else. Start it with:

    docker run -d --name fraud-ring-scratch-neo4j -p 7688:7687 -e NEO4J_AUTH=neo4j/scratch-test-password neo4j:5.26-community

If it is not running, these tests are skipped. They need no API key: no LLM call is possible
(the key is blanked), so every page must come from the saved answers in data/cache/.
"""

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from src import config
from src.data_loading.load_documents_into_graph import (
    load_documents_into_graph,
    read_document_list,
)
from src.data_loading.load_pdfs_into_graph import load_pdfs_into_graph
from src.data_loading.load_tables_into_graph import count_graph, load_tables_into_graph
from src.graph.connection import open_neo4j_driver

CLAIMS = [
    "C-1088",
    "C-1026",
    "C-1001",
]  # a ring claim, a claim with copies, a normal claim
ID_PROPERTY = {
    "Claim": "claim_id",
    "Claimant": "claimant_id",
    "Incident": "incident_id",
    "Policy": "policy_id",
    "Vehicle": "vehicle_id",
    "Address": "address_id",
    "Phone": "number",
    "Provider": "provider_id",
    "Attorney": "attorney_id",
    "LawFirm": "law_firm_id",
    "Lawsuit": "lawsuit_id",
    "Court": "court_id",
    "Expert": "expert_id",
    "Payment": "payment_id",
    "Treatment": "treatment_id",
    "ReserveEvent": "event_id",
}


@pytest.fixture(scope="module")
def scratch():
    driver = GraphDatabase.driver(
        "bolt://localhost:7688", auth=("neo4j", "scratch-test-password")
    )
    try:
        driver.verify_connectivity()
    except (DriverError, Neo4jError, OSError):
        driver.close()
        pytest.skip("the scratch Neo4j is not running (see the top of this file)")
    driver.execute_query(
        "MATCH (n) DETACH DELETE n"
    )  # the scratch database only: it is empty and ours
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def live():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


@pytest.fixture(autouse=True)
def no_llm_calls(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")


def properties_of(driver, label):
    records, _, _ = driver.execute_query(
        f"MATCH (n:{label}) RETURN n.{ID_PROPERTY[label]} AS id, properties(n) AS p"
    )
    return {
        record["id"]: {key: str(value) for key, value in record["p"].items()}
        for record in records
    }


def test_the_tables_make_the_same_graph_as_the_live_graph(scratch, live):
    nodes, edges = load_tables_into_graph(scratch)
    live_nodes, live_edges = count_graph(live)
    for label in ID_PROPERTY:
        assert nodes[label] == live_nodes[label], label
    for edge_type, count in edges.items():
        assert count == live_edges[edge_type], edge_type
    for label in ID_PROPERTY:
        scratch_properties, live_properties = (
            properties_of(scratch, label),
            properties_of(live, label),
        )
        assert scratch_properties.keys() == live_properties.keys(), label
        for node_id, properties in scratch_properties.items():
            # The live graph has more properties on 9 claims (risk_score, band ...): the old review step wrote them.
            for key, value in properties.items():
                assert live_properties[node_id][key] == value, (label, node_id, key)


def test_loading_the_tables_again_changes_nothing(scratch):
    before = count_graph(scratch)
    assert load_tables_into_graph(scratch) == before


def test_the_documents_equal_the_live_graph(scratch, live):
    assert load_documents_into_graph(scratch, read_document_list()) == 2826
    query = "MATCH (c:Claim)-[:HAS_DOCUMENT]->(d:Document) RETURN d.document_id AS id, c.claim_id AS claim, properties(d) AS p"
    for driver_query in (query,):
        scratch_rows = {
            r["id"]: (
                r["claim"],
                {
                    k: str(v)
                    for k, v in r["p"].items()
                    if k in ("document_type", "file_name", "page_count")
                },
            )
            for r in scratch.execute_query(driver_query)[0]
        }
        live_rows = {
            r["id"]: (
                r["claim"],
                {
                    k: str(v)
                    for k, v in r["p"].items()
                    if k in ("document_type", "file_name", "page_count")
                },
            )
            for r in live.execute_query(driver_query)[0]
        }
        assert scratch_rows == live_rows


def test_the_pdf_data_of_three_claims_equals_the_live_graph(scratch, live):
    summary = load_pdfs_into_graph(scratch, CLAIMS)
    assert summary["warnings"] == [] or all(
        "ignored" in warning for warning in summary["warnings"]
    )

    chunk_query = (
        "MATCH (c:Claim)-[:HAS_DOCUMENT]->(:Document)-[:HAS_CHUNK]->(k:Chunk) WHERE c.claim_id IN $claims "
        "RETURN k.chunk_id AS id, k.text AS text, k.page_number AS page, k.embedding AS embedding"
    )
    scratch_chunks = {
        r["id"]: r for r in scratch.execute_query(chunk_query, claims=CLAIMS)[0]
    }
    live_chunks = {
        r["id"]: r for r in live.execute_query(chunk_query, claims=CLAIMS)[0]
    }
    assert scratch_chunks.keys() == live_chunks.keys() and len(scratch_chunks) > 20
    for chunk_id, chunk in scratch_chunks.items():
        assert (chunk["text"], chunk["page"]) == (
            live_chunks[chunk_id]["text"],
            live_chunks[chunk_id]["page"],
        )
        assert (
            max(
                abs(a - b)
                for a, b in zip(chunk["embedding"], live_chunks[chunk_id]["embedding"])
            )
            < 1e-4
        )

    finding_query = (
        "MATCH (c:Claim)-[:HAS_FINDING]->(f:Finding)-[:FOUND_IN]->(d:Document) WHERE c.claim_id IN $claims "
        "RETURN f.finding_id AS id, d.document_id AS document, properties(f) AS p"
    )

    def findings(driver):
        return {
            r["id"]: (r["document"], {k: str(v) for k, v in r["p"].items()})
            for r in driver.execute_query(finding_query, claims=CLAIMS)[0]
        }

    assert findings(scratch) == findings(live) and len(findings(scratch)) > 30

    mention_query = (
        "MATCH (c:Claim)-[:HAS_DOCUMENT]->(d:Document)-[m:MENTIONS]->(n) WHERE c.claim_id IN $claims "
        "RETURN d.document_id AS document, m.page_number AS page, labels(n)[0] AS label, "
        "coalesce(n.claim_id, n.claimant_id, n.number, n.address_id, n.provider_id, n.attorney_id, "
        "n.law_firm_id, n.expert_id, n.court_id, n.vehicle_id, n.policy_id) AS node, "
        "m.match_method AS method, m.value_as_written AS written"
    )

    def mentions(driver):
        return sorted(
            tuple(map(str, r.values()))
            for r in driver.execute_query(mention_query, claims=CLAIMS)[0]
        )

    assert mentions(scratch) == mentions(live) and len(mentions(scratch)) > 10

    loss_date_query = (
        "MATCH (c:Claim)-[:HAS_DOCUMENT]->(d:Document) WHERE c.claim_id IN $claims "
        "RETURN d.document_id AS id, toString(d.loss_date_in_pdf) AS day, "
        "d.loss_date_page_number AS page, d.loss_date_conflict AS conflict"
    )

    def loss_dates(driver):
        return {
            r["id"]: (r["day"], r["page"], r["conflict"])
            for r in driver.execute_query(loss_date_query, claims=CLAIMS)[0]
        }

    assert loss_dates(scratch) == loss_dates(live)


def test_loading_the_pdfs_again_gives_no_copies(scratch):
    before = count_graph(scratch)
    load_pdfs_into_graph(scratch, ["C-1088"])
    assert count_graph(scratch) == before


def test_an_unknown_claim_is_refused(scratch):
    with pytest.raises(ValueError, match="C-9999"):
        load_pdfs_into_graph(scratch, ["C-9999"])
