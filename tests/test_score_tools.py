"""Tests of src/tools/score_tools.py (new system). They run on the real graph (Neo4j must be running)."""

import datetime
import json

import pytest

from src.graph.connection import open_neo4j_driver
from src.scoring.engine import score_facts
from src.scoring.facts import read_claim_facts
from src.tools.checks import run_for_claim
from src.tools.score_tools import get_claim_score, make_json_safe

ATTACK = "MATCH (n) DETACH DELETE n"


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def count_nodes(driver):
    records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    return records[0]["nodes"]


def test_make_json_safe_turns_dates_into_text():
    result = make_json_safe(
        {
            "day": datetime.date(2024, 12, 16),
            "list": [datetime.date(2024, 1, 2)],
            "n": 5,
        }
    )
    assert result == {"day": "2024-12-16", "list": ["2024-01-02"], "n": 5}


def test_the_ring_claim_answer_has_the_engine_numbers(driver):
    answer = get_claim_score(driver, "C-1088")
    score = answer["facts"]
    expected = score_facts(read_claim_facts(driver, "C-1088"))
    assert score["total_score"] == expected["total_score"] == 22.2
    assert score["band"] == "High"
    assert [
        (rule["rule_id"], rule["points_in_total"]) for rule in score["fired_rules"]
    ] == [
        ("BI-2", 5.26),
        ("BI-3", 3.51),
        ("BI-5", 2.63),
        ("BI-6", 3.51),
        ("NL-3", 4.24),
        ("NL-6", 3.03),
    ]


def test_the_proof_is_there_and_is_text(driver):
    score = get_claim_score(driver, "C-1088")["facts"]
    bi_5 = next(rule for rule in score["fired_rules"] if rule["rule_id"] == "BI-5")
    assert set(bi_5["proof"]) == {"attorney_retained_date", "first_visit_date"}
    assert isinstance(bi_5["proof"]["first_visit_date"], str)
    json.dumps(
        get_claim_score(driver, "C-1088")
    )  # no error: the whole answer can be sent as JSON


def test_the_not_evaluated_rules_are_named(driver):
    score = get_claim_score(driver, "C-1088")["facts"]
    # C-1088 has no lawsuit (CT-7, NL-5 cannot run) and no occupants_listed finding (AS-6 cannot run).
    assert score["not_evaluated_rule_ids"] == ["AS-6", "CT-7", "NL-5"]
    assert "BI-5" not in score["not_evaluated_rule_ids"]
    assert score["coverage_pct"] < 100


def test_the_answer_has_notes_and_sources(driver):
    answer = get_claim_score(driver, "C-1088")
    assert any("Coverage" in note for note in answer["notes"])
    assert any("not a finding of fraud" in note for note in answer["notes"])
    assert answer["sources"]


def test_a_missing_claim_gives_a_message(driver):
    assert get_claim_score(driver, "C-9999") == {
        "message": "Claim C-9999 was not found in the graph."
    }


def test_through_the_gate_a_bad_value_runs_nothing(driver):
    before = count_nodes(driver)
    assert "not a claim ID" in run_for_claim(driver, ATTACK, get_claim_score)["message"]
    assert (
        run_for_claim(driver, " c-1088 ", get_claim_score)["facts"]["claim_id"]
        == "C-1088"
    )
    assert count_nodes(driver) == before


def test_the_tool_does_not_change_the_graph(driver):
    before = count_nodes(driver)
    for number in range(1001, 1101, 10):
        get_claim_score(driver, f"C-{number}")
    assert count_nodes(driver) == before
