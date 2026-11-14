"""Tests of src/tools/portfolio_tools.py and check_band (new system). They run on the real graph (Neo4j must be running).

The saved scores are compared with the scoring engine, called directly on a sample of claims, so a stale snapshot is found.
"""

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.scoring.engine import score_facts
from src.scoring.facts import read_claim_facts
from src.tools.checks import check_band
from src.tools.portfolio_tools import BAND_NAMES, list_claims_by_score

ATTACK = "MATCH (n) DETACH DELETE n"


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def test_a_band_is_cleaned_and_a_bad_band_is_refused():
    assert check_band(" HIGH ") == ("High", None)
    assert check_band("very_high") == ("Very High", None)
    assert check_band("Very  High")[0] is None  # two spaces: refused, never guessed
    assert check_band("any") == ("any", None)
    for bad in [ATTACK, "", "critical", None, 5]:
        band, problem = check_band(bad)
        assert band is None and "must be one of" in problem


def test_the_band_names_are_the_bands_of_the_scoring_engine():
    assert BAND_NAMES == ["Very High", "High", "Medium", "Low"]


def test_the_counts_cover_every_claim(driver):
    facts = list_claims_by_score(driver, "any")["facts"]
    assert (
        sum(facts["band_counts"].values())
        == facts["claims_with_saved_score"]
        == facts["claims_in_graph"]
        == config.TOTAL_CLAIMS
    )
    assert facts["matching_claim_count"] == 500


def test_the_top_claims_come_highest_first_with_a_fixed_order_for_ties(driver):
    top = list_claims_by_score(driver, "any")["facts"]["top_claims"]
    assert len(top) == config.MAX_CLAIMS_SHOWN_BY_SCORE
    assert [(-claim["total_score"], claim["claim_id"]) for claim in top] == sorted(
        (-claim["total_score"], claim["claim_id"]) for claim in top
    )
    assert list_claims_by_score(driver, "any") == list_claims_by_score(
        driver, "any"
    )  # the same data, the same list


def test_a_band_filter_keeps_only_that_band(driver):
    facts = list_claims_by_score(driver, "High")["facts"]
    assert facts["matching_claim_count"] == facts["band_counts"]["High"]
    assert all(claim["band"] == "High" for claim in facts["top_claims"])
    very_high = list_claims_by_score(driver, "Very High")[
        "facts"
    ]  # an empty band is an answer, not a problem
    assert (
        very_high["matching_claim_count"]
        == very_high["band_counts"]["Very High"]
        == len(very_high["top_claims"])
    )


def test_the_ring_claims_are_at_the_top(driver):
    facts = list_claims_by_score(driver, "High")["facts"]
    assert "C-1088" in [claim["claim_id"] for claim in facts["top_claims"]]
    assert (
        next(claim for claim in facts["top_claims"] if claim["claim_id"] == "C-1088")[
            "total_score"
        ]
        == 22.2
    )


def test_only_the_newest_snapshot_of_a_claim_is_used(driver):
    # C-1088 has about 48 snapshots (its score over time). It must appear once, with its newest values.
    top = list_claims_by_score(driver, "High")["facts"]["top_claims"]
    live = score_facts(read_claim_facts(driver, "C-1088"))
    rows = [claim for claim in top if claim["claim_id"] == "C-1088"]
    assert len(rows) == 1
    assert (rows[0]["total_score"], rows[0]["band"]) == (
        live["total_score"],
        live["band"],
    )


def test_the_saved_scores_equal_the_live_scores_on_a_sample(driver):
    records, _, _ = driver.execute_query(
        "MATCH (c:Claim) RETURN c.claim_id AS claim_id ORDER BY claim_id"
    )
    sample = [record["claim_id"] for record in records][::25]  # 20 claims
    saved, _, _ = driver.execute_query(
        "MATCH (c:Claim)-[:HAS_SCORE]->(s:ScoreSnapshot) WITH c, s ORDER BY s.as_of_date DESC "
        "WITH c, head(collect(s)) AS latest RETURN c.claim_id AS claim_id, latest.total_score AS total, latest.band AS band"
    )
    all_saved = {
        record["claim_id"]: (record["total"], record["band"]) for record in saved
    }
    for claim_id in sample:
        live = score_facts(read_claim_facts(driver, claim_id))
        assert all_saved[claim_id] == (live["total_score"], live["band"]), claim_id


def test_the_answer_says_the_scores_are_saved_and_not_a_finding(driver):
    answer = list_claims_by_score(driver, "any")
    assert any("saved scores" in note for note in answer["notes"]) and any(
        "not a finding of fraud" in note for note in answer["notes"]
    )
    assert (
        answer["sources"]
        and answer["facts"]["saved_scores_from"] <= answer["facts"]["saved_scores_to"]
    )


def test_the_tool_does_not_change_the_graph(driver):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    for band in ["any", "High", "Low"]:
        list_claims_by_score(driver, band)
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert after[0]["nodes"] == before[0]["nodes"]
