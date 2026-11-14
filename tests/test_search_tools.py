"""Tests of src/tools/search_tools.py and the new input checks in src/tools/checks.py (new system).

They run on the real graph (Neo4j must be running). The expected values come from the CSV files
in data/tables/ and data/pdfs/, the source of the graph, and not from the tools.
"""

import csv

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.tools.checks import check_name, check_phone, check_topic, run_for_claim
from src.tools.search_tools import (
    MAX_SEARCH_RESULTS,
    claims_linked_to_name,
    claims_with_phone,
    fuse_rankings,
    search_all_documents,
    search_claim_documents,
    words_for_keyword_search,
)

RING_B_CLAIM = "C-1088"
SHARED_PHONE = "713-555-2172"
LAW_FIRM = "Santiago & Romero Law Group"
ATTACK = "MATCH (n) DETACH DELETE n"


def read_csv(directory, file_name):
    with open(directory / file_name, encoding="utf-8") as file:
        return list(csv.DictReader(file))


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def count_nodes(driver):
    records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    return records[0]["nodes"]


# --- The input checks (no Neo4j needed) ---


@pytest.mark.parametrize(
    "text, expected",
    [
        ("713-555-0142", "713-555-0142"),
        ("(832) 555-0142", "832-555-0142"),
        ("1-832-555-0142", "832-555-0142"),
        ("555-0142", "555-0142"),
        ("5550142", "555-0142"),
    ],
)
def test_a_phone_is_cleaned(text, expected):
    assert check_phone(text) == (expected, None)


@pytest.mark.parametrize("text", ["12", "", ATTACK, "123456789", 5, None])
def test_a_bad_phone_is_refused_with_a_message(text):
    phone, message = check_phone(text)
    assert phone is None and "phone number" in message


def test_a_name_is_cut_and_a_short_name_is_refused():
    assert check_name("  Law  ") == ("Law", None)
    assert check_name("ab")[0] is None and "too short" in check_name("ab")[1]
    assert len(check_name("x" * 500)[0]) == 200
    assert check_name(None)[0] is None


def test_a_topic_must_not_be_empty():
    assert check_topic("  passenger not in the car ") == (
        "passenger not in the car",
        None,
    )
    assert check_topic("   ")[0] is None
    assert check_topic(None)[0] is None
    assert len(check_topic("y" * 500)[0]) == 200


# --- The tools ---


def test_claims_with_phone_matches_the_csv_files(driver):
    claimant_ids = {
        row["claimant_id"]
        for row in read_csv(config.TABLES_DIR, "claimants.csv")
        if row["phone_number"] == SHARED_PHONE
    }
    expected = sorted(
        row["claim_id"]
        for row in read_csv(config.TABLES_DIR, "claims.csv")
        if row["claimant_id"] in claimant_ids
    )
    answer = claims_with_phone(driver, SHARED_PHONE)
    assert [row["claim_id"] for row in answer["facts"]["claims"]] == expected
    assert len(expected) >= 3
    assert answer["sources"]


def test_the_last_seven_digits_find_the_same_claims(driver):
    assert (
        claims_with_phone(driver, "555-2172")["facts"]["claims"]
        == claims_with_phone(driver, SHARED_PHONE)["facts"]["claims"]
    )


def test_an_unknown_phone_gives_a_message(driver):
    assert (
        "No claim has a phone number"
        in claims_with_phone(driver, "000-000-0000")["message"]
    )


def test_claims_linked_to_a_law_firm_match_the_csv_files(driver):
    firm_id = next(
        row["law_firm_id"]
        for row in read_csv(config.TABLES_DIR, "law_firms.csv")
        if row["name"] == LAW_FIRM
    )
    attorney_ids = {
        row["attorney_id"]
        for row in read_csv(config.TABLES_DIR, "attorneys.csv")
        if row["law_firm_id"] == firm_id
    }
    expected = sorted(
        row["claim_id"]
        for row in read_csv(config.TABLES_DIR, "claims.csv")
        if row["attorney_id"] in attorney_ids
    )
    answer = claims_linked_to_name(driver, LAW_FIRM)
    assert answer["facts"]["claim_ids"] == expected
    assert answer["facts"]["link_types"] == ["LAW_FIRM"]


def test_claims_linked_to_a_clinic_include_the_ring_claim(driver):
    clinic_id = next(
        row["clinic_id"]
        for row in read_csv(config.TABLES_DIR, "claims.csv")
        if row["claim_id"] == RING_B_CLAIM
    )
    clinic_name = next(
        row["name"]
        for row in read_csv(config.TABLES_DIR, "providers.csv")
        if row["provider_id"] == clinic_id
    )
    answer = claims_linked_to_name(driver, clinic_name.upper())  # no case difference
    assert RING_B_CLAIM in answer["facts"]["claim_ids"]


def test_a_name_that_fits_several_names_asks_which_one(driver):
    assert "Which one do you mean?" in claims_linked_to_name(driver, "Law")["message"]


def test_an_unknown_name_gives_a_message(driver):
    assert "was found" in claims_linked_to_name(driver, "Nobody Zzzz Inc")["message"]


def test_the_document_search_gives_sources_that_exist(driver):
    documents = {
        row["file_name"]: int(row["page_count"])
        for row in read_csv(config.PDFS_DIR, "documents.csv")
        if row["claim_id"] == RING_B_CLAIM
    }
    answer = search_claim_documents(
        driver, RING_B_CLAIM, "passenger was not in the car"
    )
    passages = answer["facts"]["passages"]
    assert 1 <= len(passages) <= MAX_SEARCH_RESULTS
    assert [passage["similarity"] for passage in passages] == sorted(
        (p["similarity"] for p in passages), reverse=True
    )
    for passage in passages:
        file_name, page_text = passage["source"].split(", page ")
        assert file_name in documents and 1 <= int(page_text) <= documents[file_name]
    assert answer["sources"] == [passage["source"] for passage in passages]


def test_a_missing_claim_gives_a_message(driver):
    assert search_claim_documents(driver, "C-9999", "anything") == {
        "message": "Claim C-9999 was not found in the graph."
    }


def test_query_text_as_a_value_runs_nothing(driver):
    before = count_nodes(driver)
    assert (
        "not a claim ID"
        in run_for_claim(
            driver,
            ATTACK,
            lambda driver, claim_id: search_claim_documents(driver, claim_id, "x"),
        )["message"]
    )
    assert (
        "was found" in claims_linked_to_name(driver, ATTACK)["message"]
    )  # only a name that matches nothing
    assert "No claim has" in claims_with_phone(driver, "000-000-0001")["message"]
    search_claim_documents(driver, RING_B_CLAIM, ATTACK)  # only a topic to compare
    assert count_nodes(driver) == before


# --- Hybrid search over ALL documents (build step 3) ---


def test_keyword_text_keeps_only_small_words():
    # Capital AND/OR/NOT and signs like ( ) : * are commands for the full-text index. They must become plain words.
    assert words_for_keyword_search('Pain: NOT (gone) "now"*') == "pain not gone now"
    assert words_for_keyword_search("*** ::") == ""


def test_rank_fusion_puts_a_chunk_found_both_ways_first():
    # c: 1/63 + 1/61 = 0.0323. a: 1/61 = 0.0164. b and d: 1/62 each, so the smaller ID (b) comes first.
    assert fuse_rankings([["a", "b", "c"], ["c", "d"]]) == ["c", "a", "b", "d"]
    assert fuse_rankings([[], []]) == []


def test_the_hybrid_search_finds_the_words_and_adds_the_graph_facts(driver):
    documents = {
        (row["claim_id"], row["file_name"]): int(row["page_count"])
        for row in read_csv(config.PDFS_DIR, "documents.csv")
    }
    answer = search_all_documents(driver, "home stretching instructions")
    passages = answer["facts"]["passages"]
    assert 1 <= len(passages) <= MAX_SEARCH_RESULTS
    for passage in passages:
        file_name, page_text = passage["source"].split(", page ")
        assert file_name.startswith(passage["claim_id"] + "_")
        assert 1 <= int(page_text) <= documents[(passage["claim_id"], file_name)]
        assert passage["found_by"] and passage["claimant"]
        assert passage["band"] in ("Very High", "High", "Medium", "Low", None)
    found_by_words = [p for p in passages if "words" in p["found_by"]]
    assert found_by_words and "stretching" in found_by_words[0]["text"].lower()
    assert answer["sources"] == [passage["source"] for passage in passages]


def test_the_hybrid_search_band_is_the_newest_saved_band(driver):
    from src.graph import queries

    records, _, _ = driver.execute_query(queries.LATEST_SCORE_OF_EVERY_CLAIM)
    newest_band = {record["claim_id"]: record["band"] for record in records}
    for passage in search_all_documents(driver, "treatment growth")["facts"][
        "passages"
    ]:
        assert passage["band"] == newest_band[passage["claim_id"]]


def test_attack_text_as_a_topic_is_only_words_and_changes_nothing(driver):
    before = count_nodes(driver)
    answer = search_all_documents(driver, ATTACK)
    assert len(answer["facts"]["passages"]) <= MAX_SEARCH_RESULTS
    assert search_all_documents(driver, "*** ::")["facts"]["passages"]  # meaning only
    assert count_nodes(driver) == before
