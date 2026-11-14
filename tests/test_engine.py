"""Tests of src/scoring/engine.py (new system).

The math tests use made-up rule results and need no Neo4j. The expected numbers are worked out
by hand (in the comments). The last tests use the real graph and compare with the saved scores.
"""

import datetime

import pytest

from src import config
from src.scoring import engine
from src.scoring.rule_results import fired_or_not, not_evaluated
from src.scoring.rules_catalog import RULES

LOSS = datetime.date(2024, 12, 15)


def all_rules_as(status):
    return {rule.rule_id: {"status": status, "proof": {}} for rule in RULES}


def test_the_weights_add_up_to_one():
    assert sum(config.CATEGORY_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_rule_fired_gives_100_and_very_high():
    result = engine.score_rule_results(all_rules_as("fired"))
    assert result["total_score"] == 100.0
    assert result["band"] == "Very High"
    assert result["category_scores"] == {
        "BI": 100.0,
        "AS": 100.0,
        "BF": 100.0,
        "CT": 100.0,
        "NL": 100.0,
    }
    assert result["coverage_pct"] == 100.0
    assert len(result["fired_rules"]) == 32


def test_no_rule_fired_gives_0_and_low():
    result = engine.score_rule_results(all_rules_as("not_fired"))
    assert (result["total_score"], result["band"], result["coverage_pct"]) == (
        0.0,
        "Low",
        100.0,
    )
    assert result["fired_rules"] == []


def test_a_missing_input_lowers_the_coverage_but_not_the_score():
    result = engine.score_rule_results(all_rules_as("not_evaluated"))
    assert (result["total_score"], result["band"], result["coverage_pct"]) == (
        0.0,
        "Low",
        0.0,
    )


def test_a_worked_example_with_one_fired_rule():
    # BI-5 (6 points) fires, the other 31 rules do not. BI has 57 points in all.
    # Category BI: 6 / 57 x 100 = 10.526 -> 10.5. Total: 0.25 x 10.526 = 2.63 -> 2.6.
    # BI-5 adds 0.25 x 6 / 57 x 100 = 2.63 to the total.
    rule_results = all_rules_as("not_fired")
    rule_results["BI-5"] = fired_or_not(True, {"why": "test"})
    result = engine.score_rule_results(rule_results)
    assert result["category_scores"]["BI"] == 10.5
    assert result["total_score"] == 2.6
    assert result["band"] == "Low"
    assert [
        (rule["rule_id"], rule["points"], rule["points_in_total"])
        for rule in result["fired_rules"]
    ] == [("BI-5", 6, 2.63)]
    assert result["fired_rules"][0]["proof"] == {"why": "test"}


@pytest.mark.parametrize(
    "total_score, band",
    [
        (100, "Very High"),
        (30, "Very High"),
        (29.9, "High"),
        (20, "High"),
        (19.9, "Medium"),
        (10, "Medium"),
        (9.9, "Low"),
        (0, "Low"),
    ],
)
def test_the_band_limits(total_score, band):
    assert engine.band_for(total_score)[0] == band


def test_the_action_comes_with_the_band():
    assert engine.band_for(25)[1] == "Assign an investigator."


def facts_with(**changes):
    facts = {
        "claim_id": "C-0000",
        "loss_date": LOSS,
        "attorney_retained_date": LOSS + datetime.timedelta(days=1),
        "visit_dates": [LOSS + datetime.timedelta(days=8)],
        "direct_links": [],
        "reported_date": LOSS + datetime.timedelta(days=2),
        "policy": None,
        "lawsuits": [],
        "repair_estimate_amount": None,
        "payments": [],
        "reserve_events": [],
        "repeat_claims": [],
        "cluster_claim_ids": ["C-0000"],
        "document_loss_dates": [],
        "findings": {},
        "incident_id": None,
        "incident_claimant_count": None,
        "has_story_text": False,
        "copied_story": [],
    }
    facts.update(changes)
    return facts


def test_a_rule_without_a_check_is_not_evaluated(monkeypatch):
    # All 32 rules have a check now. Take one away for this test only.
    monkeypatch.delitem(engine.RULE_CHECKS, "NL-4")
    results = engine.run_rules(facts_with())
    assert list(results) == [rule.rule_id for rule in RULES]  # all 32, in catalog order
    assert results["NL-4"] == not_evaluated("no check is written for this rule yet")
    assert results["BI-5"]["status"] == "fired"


def test_the_same_facts_give_the_same_score():
    assert engine.score_facts(facts_with()) == engine.score_facts(facts_with())


def test_a_coverage_example():
    # facts_with has no policy, no lawsuit, no reserve and no repair estimate. So CT-1, CT-2, CT-3, CT-7,
    # BF-1, BF-2, BF-4 and NL-5 are not evaluated. The attorney is known, so these run:
    # BI-5 (6), BI-6 (8), NL-3 (14), CT-4 (6), BF-3 (6), NL-1 (8), NL-2 (8) and NL-6 (10): 66 points of 352.
    # 66 / 352 x 100 = 18.75 -> 18.8.
    assert engine.score_facts(facts_with())["coverage_pct"] == 18.8
    # Without an attorney, BI-5 and NL-3 are not evaluated: BI-6 (8), CT-4 (6), BF-3 (6), NL-1 (8), NL-2 (8), NL-6 (10) count.
    # 46 / 352 x 100 = 13.07 -> 13.1.
    assert (
        engine.score_facts(facts_with(attorney_retained_date=None))["coverage_pct"]
        == 13.1
    )


# --- With the real graph, and the old engine as reference ---


@pytest.fixture(scope="module")
def driver():
    from src.graph.connection import open_neo4j_driver

    driver = open_neo4j_driver()
    yield driver
    driver.close()


def test_the_ring_claim_scores_from_its_six_rules(driver):
    from src.scoring.facts import read_claim_facts

    result = engine.score_facts(read_claim_facts(driver, "C-1088"))
    # The old engine gave these rules these shares for C-1088: BI-2 5.26, BI-3 3.51, BI-5 2.63,
    # BI-6 3.51, NL-3 4.24, NL-6 3.03.
    assert [
        (rule["rule_id"], rule["points_in_total"]) for rule in result["fired_rules"]
    ] == [
        ("BI-2", 5.26),
        ("BI-3", 3.51),
        ("BI-5", 2.63),
        ("BI-6", 3.51),
        ("NL-3", 4.24),
        ("NL-6", 3.03),
    ]
    assert result["total_score"] == 22.2  # the shares add up to 22.18 -> 22.2
    assert result["band"] == "High"
    assert result["claim_id"] == "C-1088"


def test_every_score_equals_the_newest_saved_score(driver):
    # The score is repeatable: the same data gives the same score (CLAUDE.md, section 7). The saved
    # snapshots were made by the pipeline, so working the score out again must give the same values.
    from src.graph import queries
    from src.scoring.facts import read_claim_facts

    records, _, _ = driver.execute_query(queries.LATEST_SCORE_OF_EVERY_CLAIM)
    for record in records:
        result = engine.score_facts(read_claim_facts(driver, record["claim_id"]))
        fired_rule_ids = [rule["rule_id"] for rule in result["fired_rules"]]
        assert (result["total_score"], result["band"], sorted(fired_rule_ids)) == (
            record["total_score"],
            record["band"],
            sorted(record["fired_rule_ids"]),
        ), record["claim_id"]
