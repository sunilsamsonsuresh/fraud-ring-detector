"""Tests of src/tools/checks.py (new system). Only the last test needs Neo4j."""

import pytest

from src.graph.connection import open_neo4j_driver
from src.tools.checks import MAX_SHOWN_CHARACTERS, check_claim_id, run_for_claim
from src.tools.claim_tools import get_claim_record


@pytest.mark.parametrize("text", ["C-1026", " c-1026 ", "c-1026\n", "\tC-1026"])
def test_a_claim_id_is_cleaned(text):
    assert check_claim_id(text) == ("C-1026", None)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "C-102",
        "C-10266",
        "X-1026",
        "C1026",
        "C-10 26",
        "C-1026 and C-1027",
        "C-١٠٢٦",  # digits of another alphabet
        "C-1026\nC-1027",
        "MATCH (n) DETACH DELETE n",
        "C-1026'; DROP",
        None,
        1026,
        ["C-1026"],
    ],
)
def test_a_wrong_value_is_refused_with_a_message(text):
    claim_id, problem = check_claim_id(text)
    assert claim_id is None
    assert "claim ID looks like C-1026" in problem


def test_a_very_long_value_is_cut_in_the_message():
    _, problem = check_claim_id("x" * 10_000)
    assert len(problem) < 100 + MAX_SHOWN_CHARACTERS


def test_a_good_value_reaches_the_tool_cleaned():
    calls = []

    def recording_tool(driver, claim_id):
        calls.append((driver, claim_id))
        return {"facts": claim_id}

    assert run_for_claim("the driver", " c-1026 ", recording_tool) == {
        "facts": "C-1026"
    }
    assert calls == [("the driver", "C-1026")]


def test_a_wrong_value_never_reaches_the_tool():
    calls = []

    def recording_tool(driver, claim_id):
        calls.append(claim_id)
        return {"facts": claim_id}

    result = run_for_claim("the driver", "MATCH (n) DETACH DELETE n", recording_tool)
    assert "message" in result and "facts" not in result
    assert calls == []


def test_the_gate_works_with_a_real_tool():
    driver = open_neo4j_driver()
    try:
        assert (
            run_for_claim(driver, " c-1088 ", get_claim_record)["facts"]["claim_id"]
            == "C-1088"
        )
        assert (
            "claim ID looks like"
            in run_for_claim(driver, "C-88", get_claim_record)["message"]
        )
        assert run_for_claim(driver, "C-9999", get_claim_record)["message"].endswith(
            "not found in the graph."
        )
    finally:
        driver.close()
