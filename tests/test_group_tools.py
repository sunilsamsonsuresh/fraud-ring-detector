"""Tests of src/tools/group_tools.py and check_group_kind (new system). They run on the real graph (Neo4j must be running)."""

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.tools.checks import GROUP_KINDS, check_group_kind
from src.tools.group_tools import (
    GROUP_QUERIES,
    MAX_CLAIM_IDS_PER_GROUP,
    find_shared_groups,
)

ATTACK = "MATCH (n) DETACH DELETE n"


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def test_the_checked_kinds_and_the_queries_are_the_same_list():
    assert sorted(GROUP_KINDS) == sorted(GROUP_QUERIES)


def test_a_kind_is_cleaned_and_a_bad_kind_is_refused():
    assert check_group_kind(" Address ") == ("address", None)
    for bad in [ATTACK, "", "claim", None, 5]:
        kind, problem = check_group_kind(bad)
        assert kind is None and "must be one of" in problem


@pytest.mark.parametrize("kind", GROUP_KINDS)
def test_every_kind_gives_groups_with_the_expected_shape(driver, kind):
    answer = find_shared_groups(driver, kind)
    facts = answer["facts"]
    assert facts["kind"] == kind and facts["group_count"] >= len(facts["groups"]) >= 1
    assert len(facts["groups"]) <= config.MAX_SHARED_GROUPS_SHOWN
    for group in facts["groups"]:
        assert group["claim_count"] >= facts["min_claims_per_group"]
        assert 1 < len(group["claim_ids"]) <= MAX_CLAIM_IDS_PER_GROUP
    assert any("not proof" in note for note in answer["notes"]) and answer["sources"]


def test_the_ring_groups_are_found(driver):
    clinic_groups = find_shared_groups(driver, "clinic_and_attorney")["facts"]["groups"]
    ring = next(
        group
        for group in clinic_groups
        if group["shared_value"] == "Harrington Physical Therapy + David Richardson"
    )
    assert (
        "C-1088" in ring["claim_ids"] and ring["claim_count"] == 11
    )  # C-1088 and its 10 linked claims


def test_family_notes_are_only_on_phone_and_address(driver):
    assert any(
        "Family" in note for note in find_shared_groups(driver, "address")["notes"]
    )
    assert not any(
        "Family" in note
        for note in find_shared_groups(driver, "clinic_and_attorney")["notes"]
    )


def test_the_tool_does_not_change_the_graph(driver):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    for kind in GROUP_KINDS:
        find_shared_groups(driver, kind)
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert after[0]["nodes"] == before[0]["nodes"]
