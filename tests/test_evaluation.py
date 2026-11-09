"""V15 tests: the metrics on a worked example, the router question file, and the claim selection.
No LLM and no Neo4j."""

import collections

from src.agents.question_router import INTENTS
from src.evaluation.layers import NETWORK_RULE_IDS, without_network
from src.evaluation.metrics import layer_metrics, precision_in_top
from src.evaluation.router_check import load_router_questions
from src.evaluation.run import agent_claims, failure_list


def row(claim_id, is_fraud, band, score, fraud_type=None, lookalike=None):
    return {"claim_id": claim_id, "is_fraud": is_fraud, "fraud_type": fraud_type, "lookalike_group": lookalike,
            "total_score": score, "band": band, "fired_rules": []}


# 5 claims worked out by hand:
#   Medium+ flags C-1, C-2, C-3 -> 2 fraud of 3 flagged = precision 2/3; 2 of 3 fraud found = recall 2/3.
#   High+ flags C-1 only -> precision 1/1, recall 1/3.
ROWS = [row("C-1", True, "High", 25.0, "ring_a"), row("C-2", True, "Medium", 12.0, "ring_a"),
        row("C-3", False, "Medium", 11.0, lookalike="family"), row("C-4", True, "Low", 5.0, "build_up"),
        row("C-5", False, "Low", 1.0, lookalike="family")]


def test_metrics_on_a_worked_example():
    metrics = layer_metrics(ROWS)
    assert metrics["at_medium"]["precision"] == 2 / 3 and metrics["at_medium"]["recall"] == 2 / 3
    assert metrics["at_high"]["precision"] == 1.0 and metrics["at_high"]["recall"] == 1 / 3
    assert metrics["recall_by_fraud_type_at_medium"] == {"build_up": (0, 1), "ring_a": (2, 2)}
    assert metrics["lookalike_false_alarms_at_medium"] == {"family": (1, 2)}
    assert metrics["band_table"]["Medium"] == {"fraud": 1, "honest": 1}
    assert precision_in_top(ROWS, count=2) == 1.0          # C-1 and C-2 are the top 2


def test_nothing_flagged_gives_an_unknown_precision_not_zero():
    metrics = layer_metrics([row("C-1", True, "Low", 1.0, "ring_a")])
    assert metrics["at_high"]["precision"] is None and metrics["at_high"]["recall"] == 0.0


def test_layer_a_has_no_network_rules():
    results = without_network({"NL-1": {"status": "fired", "proof": {}}, "BI-1": {"status": "fired", "proof": {}}})
    assert results["NL-1"]["status"] == "not_evaluated" and results["BI-1"]["status"] == "fired"
    assert len(NETWORK_RULE_IDS) == 6


def test_router_questions_cover_every_intent_five_times():
    questions = load_router_questions()
    assert len(questions) == 40
    assert collections.Counter(item["intent"] for item in questions) == {intent: 5 for intent in INTENTS}
    assert len({item["question"] for item in questions}) == 40


def test_agent_claims_are_high_claims_first_then_honest_lookalikes():
    layer_rows = {"c_plus_challenger": [row("C-9", False, "Low", 0.0, lookalike="family"),
                                        row("C-1", True, "High", 25.0, "ring_a"),
                                        row("C-2", True, "Low", 2.0, "ring_a", lookalike="family"),
                                        row("C-3", False, "Very High", 31.0, lookalike="busy_law_firm")]}
    assert agent_claims(layer_rows) == ["C-1", "C-3", "C-9"]     # C-2 is fraud, so it is not a lookalike


def test_failure_list_names_missed_fraud_and_false_alarms():
    failures = failure_list({"c_plus_challenger": ROWS}, [], [])
    assert [item["claim_id"] for item in failures["fraud_missed_low"]] == ["C-4"]
    assert [item["claim_id"] for item in failures["honest_flagged_medium_or_above"]] == ["C-3"]
