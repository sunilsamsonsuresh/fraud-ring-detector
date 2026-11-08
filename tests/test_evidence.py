"""Step 7 tests: embeddings, saved chunks, text search inside claims, copied text, Evidence agent.

Needs Neo4j and the chunks: python main.py ingest-documents --chunks
No LLM is used. The embedding model runs on this computer.
"""

import csv
import json

import pytest

from src import config
from src.agents.evidence import evidence
from src.documents.embedder import embed_texts
from src.graph.connection import open_neo4j_driver
from src.graph.retrieval import find_similar_chunks_anywhere, search_text_in_claims

NEEDS_V1_DATA = "needs v1 data; replaced in V6 or V7 (v2 chunks) and V8 (copied stories)"


@pytest.fixture(scope="module")
def driver():
    neo4j_driver = open_neo4j_driver()
    records, _, _ = neo4j_driver.execute_query("MATCH (piece:Chunk) RETURN count(piece) AS count")
    if records[0]["count"] == 0:
        neo4j_driver.close()
        pytest.fail("No chunks in Neo4j. Run: python main.py ingest-documents --chunks")
    yield neo4j_driver
    neo4j_driver.close()


@pytest.fixture(scope="module")
def ring_a_claim_ids():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)["rings"][0]["claim_ids"]


def test_embeddings_have_384_numbers_and_follow_meaning():
    rear_end, also_rear_end, weather = embed_texts(["a car hit me from behind", "I was rear-ended at a light",
                                                    "the weather is nice today"])
    assert len(rear_end) == config.EMBEDDING_DIMENSIONS

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))
    assert dot(rear_end, also_rear_end) > dot(rear_end, weather)
    assert embed_texts([]) == []


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_every_document_has_chunks_with_a_page_number(driver):
    with open(config.PDFS_DIR / "documents.csv", newline="", encoding="utf-8") as csv_file:
        document_ids = {row["document_id"] for row in csv.DictReader(csv_file)}
    records, _, _ = driver.execute_query(
        "MATCH (document:Document)-[:HAS_CHUNK]->(piece:Chunk) "
        "RETURN document.document_id AS document_id, min(piece.page_number) AS first_page, "
        "max(piece.page_number) AS last_page, document.page_count AS page_count")
    assert {record["document_id"] for record in records} == document_ids
    for record in records:
        assert record["first_page"] == 1 and record["last_page"] <= record["page_count"]


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_question_about_ring_a_returns_only_ring_a_chunks(driver, ring_a_claim_ids):
    results = search_text_in_claims(driver, "How did the rear-end collision in Pasadena happen?",
                                    ring_a_claim_ids, limit=20)
    assert len(results) == 20
    for result in results:
        assert result["claim_id"] in ring_a_claim_ids
        assert result["file_name"].endswith(".pdf") and result["page_number"] >= 1
    scores = [result["score"] for result in results]
    assert scores == sorted(scores, reverse=True)
    assert search_text_in_claims(driver, "anything", [], limit=5) == []


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_copied_ring_a_story_is_found_anywhere_with_the_vector_index(driver, ring_a_claim_ids):
    # Chunk 2 of the first Ring A claim's FNOL holds the claimant's story.
    story_chunk_id = f"{ring_a_claim_ids[0]}-fnol-p1-c2"
    results = find_similar_chunks_anywhere(driver, story_chunk_id, limit=10)
    ring_a_results = [result for result in results if result["claim_id"] in ring_a_claim_ids]
    assert len(ring_a_results) >= 8
    assert results[0]["score"] >= config.COPIED_TEXT_MIN_SCORE


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_evidence_agent_searches_only_the_linked_claims(driver, ring_a_claim_ids):
    state = {"claim_id": ring_a_claim_ids[0],
             "linked_claims": [{"claim_id": claim_id} for claim_id in ring_a_claim_ids[1:]]}
    result = evidence(state)

    assert result["evidence_claim_ids"] == ring_a_claim_ids
    for snippets in result["evidence_snippets"].values():
        assert len(snippets) == 5
        for snippet in snippets:
            assert snippet["claim_id"] in ring_a_claim_ids
            assert snippet["source"].endswith(f"page {snippet['page_number']}")
    story_documents = {snippet["document_id"].split("-", 2)[2] for snippet in result["evidence_snippets"]["accident_story"]}
    assert story_documents == {"fnol"}
    copied_from = {copy["other_claim_id"] for copy in result["copied_text"]}
    assert len(copied_from) >= 3 and copied_from <= set(ring_a_claim_ids[1:])
    assert all(copy["score"] >= config.COPIED_TEXT_MIN_SCORE for copy in result["copied_text"])


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_innocent_family_claims_have_no_copied_text(driver):
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        family = json.load(file)["innocent_overlaps"][0]["claim_ids"]
    result = evidence({"claim_id": family[0], "linked_claims": [{"claim_id": family[1]}]})
    assert result["copied_text"] == []


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_claim_without_chunks_gives_an_error(driver):
    assert "has no text chunks" in evidence({"claim_id": "C-9999"})["error_message"]
