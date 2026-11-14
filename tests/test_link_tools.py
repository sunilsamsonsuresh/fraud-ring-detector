"""Tests of src/tools/link_tools.py (new system). They run on the real graph (Neo4j must be running).

The expected links are worked out from the CSV files in data/tables/ with plain Python,
a different way than the Cypher queries use.
"""

import csv
import json

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.tools import link_tools
from src.tools.link_tools import (
    MAX_LINKED_CLAIMS,
    find_cluster,
    find_direct_links,
    get_claim_neighbourhood,
)


def read_table(file_name):
    with open(config.TABLES_DIR / file_name, encoding="utf-8") as file:
        return list(csv.DictReader(file))


CLAIMS = {row["claim_id"]: row for row in read_table("claims.csv")}
CLAIMANTS = {row["claimant_id"]: row for row in read_table("claimants.csv")}
LAWSUITS = {row["claim_id"]: row for row in read_table("lawsuits.csv")}


def expected_links(claim_id):
    """{(linked claim ID, kind)} from the CSV files. Claims of the same incident are left out."""
    source = CLAIMS[claim_id]
    source_person = CLAIMANTS[source["claimant_id"]]
    found = set()
    for other_id, other in CLAIMS.items():
        if other_id == claim_id or other["incident_id"] == source["incident_id"]:
            continue
        other_person = CLAIMANTS[other["claimant_id"]]
        if other_person["phone_number"] == source_person["phone_number"]:
            found.add((other_id, "phone"))
        if other_person["address_id"] == source_person["address_id"]:
            found.add((other_id, "address"))
        if (
            source["clinic_id"]
            and other["clinic_id"] == source["clinic_id"]
            and source["attorney_id"]
            and other["attorney_id"] == source["attorney_id"]
        ):
            found.add((other_id, "clinic_and_attorney"))
        if (
            claim_id in LAWSUITS
            and other_id in LAWSUITS
            and LAWSUITS[other_id]["plaintiff_law_firm_id"]
            == LAWSUITS[claim_id]["plaintiff_law_firm_id"]
            and LAWSUITS[other_id]["expert_id"] == LAWSUITS[claim_id]["expert_id"]
        ):
            found.add((other_id, "firm_and_expert"))
    return found


def actual_links(result):
    return {
        (item["claim_id"], link["kind"])
        for item in result["facts"]["linked_claims"]
        for link in item["links"]
    }


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def test_the_ring_claim_is_linked_through_its_clinic_and_attorney(driver):
    result = get_claim_neighbourhood(driver, "C-1088")
    linked = {item["claim_id"] for item in result["facts"]["linked_claims"]}
    assert {
        "C-1085",
        "C-1123",
        "C-1297",
        "C-1313",
        "C-1318",
        "C-1351",
        "C-1355",
        "C-1385",
        "C-1463",
        "C-1496",
    } <= linked
    reason = result["facts"]["linked_claims"][0]["links"][0]
    assert reason == {
        "kind": "clinic_and_attorney",
        "shared_value": "Harrington Physical Therapy + David Richardson",
    }
    assert result["sources"] and result["notes"]


def test_one_claim_can_be_linked_in_several_ways(driver):
    result = get_claim_neighbourhood(driver, "C-1026")
    kinds_by_claim = {
        item["claim_id"]: {link["kind"] for link in item["links"]}
        for item in result["facts"]["linked_claims"]
    }
    assert {"phone", "address"} <= kinds_by_claim["C-1209"]


def test_claims_of_the_same_incident_are_not_linked(driver):
    result = get_claim_neighbourhood(driver, "C-1026")
    linked = {item["claim_id"] for item in result["facts"]["linked_claims"]}
    assert (
        CLAIMS["C-1093"]["incident_id"] == CLAIMS["C-1026"]["incident_id"]
    )  # the same accident
    assert "C-1093" not in linked and "C-1439" not in linked


def test_the_firm_and_expert_link_is_found(driver):
    claim_id = next(
        claim_id
        for claim_id in LAWSUITS
        if any(kind == "firm_and_expert" for _, kind in expected_links(claim_id))
    )
    assert actual_links(get_claim_neighbourhood(driver, claim_id)) == expected_links(
        claim_id
    )


@pytest.mark.parametrize(
    "claim_id", sorted(CLAIMS)[::25]
)  # 20 claims, spread over the whole data
def test_the_links_match_the_csv_files(driver, claim_id):
    result = get_claim_neighbourhood(driver, claim_id)
    expected = expected_links(claim_id)
    assert result["facts"]["linked_claim_count"] == len(
        {other_id for other_id, _ in expected}
    )
    if result["facts"]["linked_claim_count"] <= MAX_LINKED_CLAIMS:
        assert actual_links(result) == expected


def test_the_list_is_cut_at_the_maximum_and_says_so(driver, monkeypatch):
    # No claim in the data has more than 25 links, so the test lowers the maximum to 3.
    monkeypatch.setattr(link_tools, "MAX_LINKED_CLAIMS", 3)
    result = link_tools.get_claim_neighbourhood(
        driver, "C-1088"
    )  # C-1088 has 10 linked claims
    assert len(result["facts"]["linked_claims"]) == 3
    assert result["facts"]["linked_claim_count"] == 10
    assert any("first 3" in note for note in result["notes"])


def test_the_result_can_be_sent_as_json(driver):
    json.dumps(get_claim_neighbourhood(driver, "C-1088"))


@pytest.mark.parametrize("claim_id", ["C-9999", "MATCH (n) DETACH DELETE n"])
def test_a_missing_claim_or_query_text_gives_a_message_and_changes_nothing(
    driver, claim_id
):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    result = get_claim_neighbourhood(driver, claim_id)
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert result == {"message": f"Claim {claim_id} was not found in the graph."}
    assert after[0]["nodes"] == before[0]["nodes"]


# --- find_cluster ---


def expected_cluster(claim_id, max_hops):
    """The same walk, written again on the CSV files (expected_links), for a check that does not use the code."""
    found = {claim_id}
    frontier = [claim_id]
    for _ in range(max_hops):
        next_frontier = []
        for current in frontier:
            for linked_claim_id, _ in expected_links(current):
                if linked_claim_id not in found:
                    found.add(linked_claim_id)
                    next_frontier.append(linked_claim_id)
        frontier = next_frontier
    return sorted(found)


def test_find_cluster_matches_the_walk_on_the_csv_files(driver):
    for claim_id in ["C-1088", "C-1026", "C-1001", "C-1123"]:
        for max_hops in [0, 1, 2, 3]:
            assert find_cluster(driver, claim_id, max_hops) == expected_cluster(
                claim_id, max_hops
            ), (claim_id, max_hops)


def test_find_cluster_with_0_hops_is_the_claim_alone_and_1_hop_equals_the_direct_links(
    driver,
):
    assert find_cluster(driver, "C-1088", 0) == ["C-1088"]
    direct = {link["linked_claim_id"] for link in find_direct_links(driver, "C-1088")}
    assert find_cluster(driver, "C-1088", 1) == sorted(direct | {"C-1088"})


def test_a_bigger_hop_limit_never_loses_claims(driver):
    assert set(find_cluster(driver, "C-1088", 2)) >= set(
        find_cluster(driver, "C-1088", 1)
    )
