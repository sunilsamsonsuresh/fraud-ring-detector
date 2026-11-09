"""Step 7 and V8 tests: embeddings, saved chunks, text search inside claims, copied stories,
and the Evidence agent, on the v2 data.

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
def truth():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


@pytest.fixture(scope="module")
def ring_a_claim_ids(truth):
    return truth["fraud_types"]["ring_a"]


def test_embeddings_have_384_numbers_and_follow_meaning():
    rear_end, also_rear_end, weather = embed_texts(["a car hit me from behind", "I was rear-ended at a light",
                                                    "the weather is nice today"])
    assert len(rear_end) == config.EMBEDDING_DIMENSIONS

    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))
    assert dot(rear_end, also_rear_end) > dot(rear_end, weather)
    assert embed_texts([]) == []


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


def test_copied_ring_a_story_is_found_anywhere_with_the_vector_index(driver, ring_a_claim_ids):
    # Chunk 2 of the first Ring A claim's FNOL holds the claimant's story.
    story_chunk_id = f"{ring_a_claim_ids[0]}-fnol-p1-c2"
    results = find_similar_chunks_anywhere(driver, story_chunk_id, limit=10)
    ring_a_results = [result for result in results if result["claim_id"] in ring_a_claim_ids]
    assert len(ring_a_results) >= 8
    assert results[0]["score"] >= config.SIMILARITY_THRESHOLD


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
    # v2: copies are searched in the whole portfolio, but only Ring A tells the same story.
    copied_from = {copy["other_claim_id"] for copy in result["copied_text"]}
    assert len(copied_from) >= 3 and copied_from <= set(ring_a_claim_ids[1:])
    assert all(copy["score"] >= config.SIMILARITY_THRESHOLD for copy in result["copied_text"])
    # v2: the text behind each fired rule that rests on text, with its source.
    quote_rules = {quote["rule_id"] for quote in result["rule_quotes"]}
    assert "NL-4" in quote_rules
    assert all("page" in quote["source"] and quote["quote"] for quote in result["rule_quotes"])


# xfail = a known failure that pytest reports on every run. strict=True: if it starts to pass,
# pytest says so, and the mark must be removed. The topic text was tuned on v1 documents (Step 7).
@pytest.mark.xfail(reason="v1 tuning: on v2 data the accident_story topic finds adjuster notes and "
                          "police reports instead of the claimant's FNOL story. Re-tune the topic text.",
                   strict=True)
def test_accident_story_topic_finds_the_claimants_own_story(driver, ring_a_claim_ids):
    state = {"claim_id": ring_a_claim_ids[0],
             "linked_claims": [{"claim_id": claim_id} for claim_id in ring_a_claim_ids[1:]]}
    snippets = evidence(state)["evidence_snippets"]["accident_story"]
    assert {snippet["document_id"].split("-", 2)[2] for snippet in snippets} == {"fnol"}


def test_innocent_family_claims_have_no_copied_text(driver, truth):
    family = sorted(claim_id for claim_id, claim in truth["claims"].items() if claim["group"] == "family")
    result = evidence({"claim_id": family[0], "linked_claims": [{"claim_id": family[1]}]})
    assert result["copied_text"] == []


def test_claim_without_chunks_gives_an_error(driver):
    assert "has no text chunks" in evidence({"claim_id": "C-9999"})["error_message"]
