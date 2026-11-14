"""Tests of src/tools/entity_tools.py (local search). They run on the real graph (Neo4j must be running).

The expected claims come from the CSV files in data/tables/, not from the graph queries.
"""

import csv

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.tools.entity_tools import (
    ENTITY_KINDS,
    MAX_CLAIMS_SHOWN,
    MAX_MENTIONS_SHOWN,
    find_entity,
    get_entity_context,
)

ATTACK = "MATCH (n) DETACH DELETE n"


def read_csv(file_name):
    with open(config.TABLES_DIR / file_name, encoding="utf-8") as file:
        return list(csv.DictReader(file))


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def claim_ids_of(answer):
    return sorted(claim["claim_id"] for claim in answer["facts"]["claims"])


def test_an_attorney_has_the_claims_of_the_csv_files(driver):
    attorney_id = next(
        row["attorney_id"]
        for row in read_csv("attorneys.csv")
        if row["name"] == "David Richardson"
    )
    expected = sorted(
        row["claim_id"]
        for row in read_csv("claims.csv")
        if row["attorney_id"] == attorney_id
    )
    answer = get_entity_context(driver, "David Richardson")
    assert answer["facts"]["entity"]["kind"] == "Attorney"
    assert (
        answer["facts"]["claim_count"] == len(expected)
        and claim_ids_of(answer) == expected
    )
    assert all(
        claim["roles"] == ["attorney of the claimant"]
        for claim in answer["facts"]["claims"]
    )


def test_a_clinic_and_its_claims_and_the_pages_that_mention_it(driver):
    provider = next(
        row
        for row in read_csv("providers.csv")
        if row["name"] == "Harrington Physical Therapy"
    )
    expected = sorted(
        row["claim_id"]
        for row in read_csv("claims.csv")
        if row["clinic_id"] == provider["provider_id"]
    )
    facts = get_entity_context(driver, "harrington physical therapy")[
        "facts"
    ]  # no case difference
    assert sorted(claim["claim_id"] for claim in facts["claims"]) == expected
    assert facts["documents_mentioning_count"] > 0
    for mention in facts["documents_mentioning"]:
        assert (
            mention["document_id"].startswith(mention["claim_id"] + "-")
            and mention["page_number"] is not None
        )


def test_a_phone_finds_the_claims_of_every_claimant_with_it(driver):
    claimant_ids = {
        row["claimant_id"]
        for row in read_csv("claimants.csv")
        if row["phone_number"] == "713-555-2172"
    }
    expected = sorted(
        row["claim_id"]
        for row in read_csv("claims.csv")
        if row["claimant_id"] in claimant_ids
    )
    answer = get_entity_context(driver, "(713) 555-2172")  # any phone format
    assert (
        answer["facts"]["entity"]["kind"] == "Phone"
        and claim_ids_of(answer) == expected
    )


def test_a_claimant_by_full_name(driver):
    claimant = read_csv("claimants.csv")[0]
    full_name = f"{claimant['first_name']} {claimant['last_name']}"
    expected = sorted(
        row["claim_id"]
        for row in read_csv("claims.csv")
        if row["claimant_id"] == claimant["claimant_id"]
    )
    answer = get_entity_context(driver, full_name)
    assert (
        answer["facts"]["entity"]["entity_id"] == claimant["claimant_id"]
        and claim_ids_of(answer) == expected
    )


def test_claims_come_highest_score_first_and_lists_are_cut(driver):
    facts = get_entity_context(driver, "Harrington Physical Therapy")["facts"]
    scores = [claim["total_score"] or 0 for claim in facts["claims"]]
    assert scores == sorted(scores, reverse=True)
    assert (
        len(facts["claims"]) <= MAX_CLAIMS_SHOWN
        and len(facts["documents_mentioning"]) <= MAX_MENTIONS_SHOWN
    )
    assert sum(facts["claims_by_band"].values()) == facts["claim_count"]


def test_several_matches_ask_which_one_and_none_says_so(driver):
    entity, problem = find_entity(driver, "Smith")
    assert entity is None and "Which one do you mean?" in problem
    assert "was found" in get_entity_context(driver, "Nobody Here")["message"]


def test_an_exact_name_wins_over_names_that_contain_it(driver):
    # "Richardson" matches a claimant and an attorney, the whole name only the attorney.
    assert find_entity(driver, "Richardson")[0] is None
    assert find_entity(driver, "David Richardson")[0]["kind"] == "Attorney"


def test_query_text_finds_nothing_and_changes_nothing(driver):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert "was found" in get_entity_context(driver, ATTACK)["message"]
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert before[0]["nodes"] == after[0]["nodes"]


def test_every_kind_has_an_id_property_and_a_claims_query():
    assert set(ENTITY_KINDS) == {
        "Claimant",
        "Provider",
        "Attorney",
        "LawFirm",
        "Expert",
        "Phone",
        "Address",
    }
