"""Step 8 tests: Litigation Analyst and Risk Scoring.

Needs Neo4j with the tables and the chunks. A fake LLM replaces the real one, so no
API call is made. The score itself never uses the LLM.
"""

import json
import random

import pytest

from src import config
from src.agents import litigation_analyst, risk_scoring
from src.graph.connection import open_neo4j_driver
from src.graph.retrieval import find_copied_text

NEEDS_V1_DATA = "needs v1 data; replaced in V6 or V7"


@pytest.fixture(scope="module")
def driver():
    neo4j_driver = open_neo4j_driver()
    yield neo4j_driver
    neo4j_driver.close()


@pytest.fixture(scope="module")
def ring_c_claim_ids():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)["rings"][2]["claim_ids"]


def plain_state(driver, claim_id):
    """The state the scoring reads, built without any LLM: linked claims = the hop-1 links."""
    linked_claim_ids = sorted(risk_scoring.read_graph_links(driver, claim_id))
    return {
        "claim_id": claim_id,
        "copied_text": find_copied_text(driver, claim_id, linked_claim_ids, config.COPIED_TEXT_MIN_SCORE,
                                        config.COPY_CHECK_DOCUMENT_TYPES),
        "litigation_facts": litigation_analyst.find_litigation_facts(driver, claim_id, linked_claim_ids),
    }


def fake_summary_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
    return "Copied text and the shared law firm drive this score. A human reviewer should compare the documents."


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_same_input_gives_the_same_score(driver, ring_c_claim_ids):
    state = plain_state(driver, ring_c_claim_ids[0])
    first = risk_scoring.collect_signals(state)
    shuffled_state = dict(state, copied_text=random.Random(7).sample(state["copied_text"], len(state["copied_text"])))
    second = risk_scoring.collect_signals(shuffled_state)
    assert first == second
    assert risk_scoring.total_score(first) == risk_scoring.total_score(second)


def test_score_math_caps_discounts_and_levels():
    signals = [{"name": "copied_text", "points": 25}, {"name": "shared_phone", "points": 15},
               {"name": "shared_address", "points": 15}, {"name": "law_firm_and_expert_together", "points": 15},
               {"name": "similar_demand_amounts", "points": 10}, {"name": "lawsuit_filed_near_deadline", "points": 10},
               {"name": "related_lawsuits_near_deadline", "points": 10}, {"name": "shared_clinic", "points": 5}]
    assert risk_scoring.total_score(signals) == 100                       # 105 is capped at 100
    assert risk_scoring.total_score(signals[1:3]) == 30
    assert risk_scoring.total_score(signals[1:3], ["shared_phone"]) == 22   # 15 * 0.5 = 7.5 -> 7, plus 15
    assert [risk_scoring.risk_level(score) for score in (59, 60, 29, 30)] == ["medium", "high", "low", "medium"]


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_ring_c_scores_high_because_of_litigation_signals(driver, ring_c_claim_ids):
    litigation_names = ["lawsuit_filed_near_deadline", "related_lawsuits_near_deadline",
                        "similar_demand_amounts", "law_firm_and_expert_together"]
    for claim_id in ring_c_claim_ids:
        signals = risk_scoring.collect_signals(plain_state(driver, claim_id))
        points = {signal["name"]: signal["points"] for signal in signals}
        assert risk_scoring.risk_level(risk_scoring.total_score(signals)) == "high", claim_id
        for name in litigation_names:
            assert points[name] > 0, (claim_id, name)
        # Without the litigation signals the claim would not be high.
        assert risk_scoring.total_score(signals) - sum(points[name] for name in litigation_names) \
            < config.HIGH_RISK_MIN_SCORE


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_explanation_lists_each_signal_and_its_source(driver, ring_c_claim_ids, monkeypatch):
    monkeypatch.setattr(risk_scoring, "ask_llm", fake_summary_llm)
    result = risk_scoring.risk_scoring(plain_state(driver, ring_c_claim_ids[0]))
    explanation = result["risk_explanation"]
    assert explanation.startswith("Copied text and the shared law firm")
    for signal in result["risk_signals"]:
        if signal["count"] > 0:
            assert f"- {signal['name']}: {signal['points']}/" in explanation
            assert signal["evidence"][0]["source"] in explanation
    assert "C-" in explanation and "page" in explanation and "lawsuit LS-" in explanation


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_summary_with_forbidden_words_is_replaced(driver, ring_c_claim_ids, monkeypatch):
    monkeypatch.setattr(risk_scoring, "ask_llm", lambda *arguments, **keywords: "The claimant is guilty.")
    result = risk_scoring.risk_scoring(plain_state(driver, ring_c_claim_ids[0]))
    assert "guilty" not in result["risk_explanation"]
    assert result["risk_warnings"]


def test_litigation_review_keeps_only_points_with_a_real_source():
    sources = {"C-1143_complaint.pdf, page 1"}
    answer = json.dumps({"assessment": "strengthens_concern", "reason": "Unusual timing.",
                         "points": [{"finding": "Filed 7 days before the deadline.",
                                     "source": "C-1143_complaint.pdf, page 1"},
                                    {"finding": "Invented.", "source": "C-9999_complaint.pdf, page 4"}]})
    review, warnings = litigation_analyst.parse_review("```json\n" + answer + "\n```", sources)
    assert review["assessment"] == "strengthens_concern" and len(review["points"]) == 1
    assert len(warnings) == 1
    assert litigation_analyst.parse_review('{"assessment": "fraud"}', sources)[0] is None
    assert litigation_analyst.parse_review("not json", sources)[0] is None
    guilty = json.dumps({"assessment": "neutral", "reason": "The plaintiff is guilty.", "points": []})
    assert litigation_analyst.parse_review(guilty, sources)[0] is None


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_claim_without_a_lawsuit_gets_facts_but_no_llm_call(monkeypatch):
    def llm_must_not_be_called(*arguments, **keywords):
        raise AssertionError("The LLM was called for a claim without a lawsuit.")
    monkeypatch.setattr(litigation_analyst, "ask_llm", llm_must_not_be_called)
    result = litigation_analyst.litigation_analyst({"claim_id": "C-1037", "linked_claims": []})
    assert result["litigation_facts"]["own_lawsuit"] is None
    assert result["litigation_review"] is None
