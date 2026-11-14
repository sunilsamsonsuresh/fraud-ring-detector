"""Tests of the communities (build step 5): src/data_loading/load_communities_into_graph.py and
src/tools/community_tools.py. Neo4j must be running, with the communities loaded. No LLM is called:
the report writer gets scripted fake answers.

The expected rings come from data/ground_truth.json, written by the data generator, not by this code.
"""

import json

import pytest

from src import config
from src.data_loading import load_communities_into_graph as communities_step
from src.graph.connection import open_neo4j_driver
from src.tools.checks import check_community_or_claim
from src.tools.community_tools import get_community, list_communities
from src.tools.link_tools import find_direct_links

ATTACK = "MATCH (n) DETACH DELETE n"


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


@pytest.fixture(scope="module")
def communities(driver):
    return communities_step.find_communities(driver)


def links(*claim_ids):
    return [{"linked_claim_id": claim_id} for claim_id in claim_ids]


# --- Plain functions with small examples (no Neo4j needed) ---


def test_linked_claims_form_one_group_and_small_groups_are_left_out():
    # A-B-C are joined (A to B, B to C). D-E are a pair. F has no link.
    links_of_claim = {
        "A": links("B"),
        "B": links("A", "C"),
        "C": links("B"),
        "D": links("E"),
        "E": links("D"),
        "F": [],
    }
    assert communities_step.group_linked_claims(links_of_claim, 3) == [["A", "B", "C"]]
    assert communities_step.group_linked_claims(links_of_claim, 2) == [
        ["A", "B", "C"],
        ["D", "E"],
    ]


def test_the_facts_count_what_the_claims_share_and_their_bands():
    links_of_claim = {
        "C-1": [
            {"linked_claim_id": "C-2", "kind": "phone", "shared_value": "555-0101"}
        ],
        "C-2": [
            {"linked_claim_id": "C-1", "kind": "phone", "shared_value": "555-0101"},
            {"linked_claim_id": "C-3", "kind": "address", "shared_value": "1 Main St"},
        ],
        "C-3": [
            {"linked_claim_id": "C-2", "kind": "address", "shared_value": "1 Main St"}
        ],
    }
    scores = {
        "C-1": {"total_score": 22.2, "band": "High"},
        "C-2": {"total_score": 5.0, "band": "Low"},
        "C-3": {"total_score": None, "band": None},
    }
    facts = communities_step.community_facts(
        "COM-01", ["C-1", "C-2", "C-3"], links_of_claim, scores
    )
    assert facts["shared"] == [
        {"kind": "address", "shared_value": "1 Main St", "claim_count": 2},
        {"kind": "phone", "shared_value": "555-0101", "claim_count": 2},
    ]
    assert facts["band_counts"] == {"High": 1, "Low": 1, "no score": 1}
    assert [item["claim_id"] for item in facts["highest_scores"]] == ["C-1", "C-2"]


def test_the_community_check_cleans_ids_and_refuses_other_text():
    assert check_community_or_claim(" com-01 ") == (("community", "COM-01"), None)
    assert check_community_or_claim("c-1088") == (("claim", "C-1088"), None)
    value, problem = check_community_or_claim(ATTACK)
    assert value is None and "not a community ID" in problem


# --- The report writer with a scripted fake LLM (no cost) ---


@pytest.mark.parametrize(
    "fake_report, passes",
    [
        ("Possible links that need human review: C-1 and C-2 share a phone.", True),
        ("C-9999 is part of this group.", False),  # a claim that is not in the facts
        ("The claimant is guilty.", False),
    ],
)
def test_the_report_is_checked_before_it_is_saved(monkeypatch, fake_report, passes):
    monkeypatch.setattr(
        communities_step, "ask_llm", lambda *arguments, **settings: fake_report
    )
    facts = {"community_id": "COM-01", "claim_ids": ["C-1", "C-2"]}
    report, problem = communities_step.write_community_report(facts)
    assert (report == fake_report) is passes and (problem is None) is passes


# --- The communities of the live graph ---


def test_each_community_holds_every_claim_its_claims_link_to(driver, communities):
    community_of_claim = {}
    for facts in communities:
        assert facts["claim_count"] >= config.COMMUNITY_MIN_CLAIMS
        for claim_id in facts["claim_ids"]:
            assert claim_id not in community_of_claim  # no claim is in two communities
            community_of_claim[claim_id] = facts["community_id"]
    for claim_id, community_id in community_of_claim.items():
        for link in find_direct_links(driver, claim_id):
            assert community_of_claim[link["linked_claim_id"]] == community_id


def test_the_planted_rings_are_found(communities):
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        rings = json.load(file)["fraud_types"]
    for ring_name in ["ring_a", "ring_b", "ring_c"]:
        ring = set(rings[ring_name])
        best_overlap = max(len(ring & set(facts["claim_ids"])) for facts in communities)
        # A ring claim with no strong link to the others cannot be found by links. Most of each ring is.
        assert best_overlap >= 0.8 * len(ring), ring_name


def test_the_saved_communities_equal_a_fresh_search(driver, communities):
    records, _, _ = driver.execute_query(
        "MATCH (claim:Claim)-[:IN_COMMUNITY]->(community:Community) "
        "RETURN community.community_id AS community_id, collect(claim.claim_id) AS claim_ids"
    )
    saved = {record["community_id"]: sorted(record["claim_ids"]) for record in records}
    assert saved == {facts["community_id"]: facts["claim_ids"] for facts in communities}


def test_the_list_tool_shows_the_biggest_first(driver, communities):
    answer = list_communities(driver)
    listed = answer["facts"]["communities"]
    assert answer["facts"]["community_count"] == len(communities)
    assert len(listed) == min(len(communities), config.MAX_COMMUNITIES_SHOWN)
    assert [item["claim_count"] for item in listed] == sorted(
        (item["claim_count"] for item in listed), reverse=True
    )


def test_a_claim_leads_to_its_community_and_an_unlinked_claim_gets_a_message(driver):
    answer = get_community(driver, ("claim", "C-1088"))
    assert "C-1088" in answer["facts"]["claim_ids"] and answer["facts"]["report"]
    assert "is in no community" in get_community(driver, ("claim", "C-1001"))["message"]
    assert "was not found" in get_community(driver, ("community", "COM-99"))["message"]
