"""V11 tests: the Challenger's checks and fixed adjustments, and the Litigation Analyst.

First: each adjustment on a small made-up claim (no database). Then: the checks on known claims
in Neo4j, and the agents with a fake LLM (no API call).
"""

import copy
import datetime
import json

import pytest

from src import config
from src.agents import challenger, litigation_analyst
from src.graph.connection import open_neo4j_driver
from src.scoring import adjustments, challenge_checks
from src.scoring.as_of import facts_as_of
from src.scoring.engine import run_rules, score_claim
from src.scoring.facts import read_raw_facts

LOSS = datetime.date(2024, 3, 1)


def link(linked_claim_id, kind, provider_claim_count=None, source="C-TEST"):
    return {"source_claim_id": source, "linked_claim_id": linked_claim_id, "kind": kind, "shared_value": "shared",
            "linked_reported_date": LOSS, "source_filed_date": None, "linked_filed_date": None,
            "provider_claim_count": provider_claim_count}


def made_up_raw(links):
    return {"claim_id": "C-TEST", "loss_date": LOSS, "reported_date": LOSS, "attorney_retained_date": LOSS,
            "repair_estimate_amount": None, "policy": None, "incident_id": "I-1", "incident_claimants": {"CL-1": LOSS},
            "visit_dates": [], "payments": [], "reserve_events": [], "lawsuits": [], "document_loss_dates": [],
            "all_findings": [],
            "network": {"direct_links": links, "cluster_links": copy.deepcopy(links),
                        "reported_dates": {item["linked_claim_id"]: LOSS for item in links},
                        "repeat_claims": [], "copied_story": [], "story_document_types": ["fnol"]}}


def status(raw, rule_id):
    return run_rules(facts_as_of(raw))[rule_id]["status"]


# --- Each adjustment on made-up data -----------------------------------------------

def test_same_incident_links_are_removed():
    raw = made_up_raw([link("C-MATE", "phone"), link("C-OTHER", "address")])
    adjusted, removed = adjustments.drop_same_incident_links(raw, ["C-MATE"])
    assert removed == ["C-MATE"]
    assert [item["linked_claim_id"] for item in adjusted["network"]["direct_links"]] == ["C-OTHER"]
    assert len(raw["network"]["direct_links"]) == 2                 # the original is not changed


def test_family_link_does_not_count_for_nl_1():
    raw = made_up_raw([link("C-SISTER", "phone"), link("C-SISTER", "address")])
    assert status(raw, "NL-1") == "fired"
    adjusted, removed = adjustments.drop_family_links(raw, ["C-SISTER"])
    assert removed == ["C-SISTER"] and status(adjusted, "NL-1") == "not_fired"
    with_stranger = made_up_raw([link("C-SISTER", "phone"), link("C-STRANGER", "phone")])
    adjusted, _ = adjustments.drop_family_links(with_stranger, ["C-SISTER"])
    assert status(adjusted, "NL-1") == "fired"                      # the stranger's link still counts


def test_busy_provider_link_does_not_count_unless_the_claims_share_more():
    busy = made_up_raw([link(f"C-{number}", "clinic_and_attorney", 25) for number in range(5)])
    assert status(busy, "NL-3") == "fired"
    adjusted, removed = adjustments.drop_busy_provider_links(busy)
    assert len(removed) == 5 and status(adjusted, "NL-3") == "not_fired"
    not_busy = made_up_raw([link(f"C-{number}", "clinic_and_attorney", 14) for number in range(5)])
    assert adjustments.drop_busy_provider_links(not_busy)[1] == []      # 14 claims is not busy
    shares_more = made_up_raw([link("C-0", "clinic_and_attorney", 25), link("C-0", "phone")])
    assert adjustments.drop_busy_provider_links(shares_more)[1] == []   # they also share a phone


def fired(rule_id, finding_id, confidence="High"):
    return {"status": "fired", "proof": {"findings": [{"finding_id": finding_id, "confidence": confidence}]}}


def test_same_proof_twice_counts_once():
    results = {"AS-1": fired("AS-1", "F-1"), "AS-2": fired("AS-2", "F-1"), "BI-1": fired("BI-1", "F-2")}
    adjusted, dropped = adjustments.drop_same_proof_twice(results)
    assert dropped == ["AS-1"]                                      # AS-2 has more points (20 against 8)
    assert adjusted["AS-2"]["status"] == "fired" and adjusted["BI-1"]["status"] == "fired"
    assert "same finding F-1" in adjusted["AS-1"]["proof"]["not_counted"]


def test_weak_proof_does_not_count():
    results = {"BI-1": fired("BI-1", "F-1", "Low"), "BI-2": fired("BI-2", "F-2", "Medium"),
               "BI-6": {"status": "fired", "proof": {"visits_in_first_30_days": 15}}}
    adjusted, dropped = adjustments.drop_weak_proof(results)
    assert dropped == ["BI-1"] and adjusted["BI-2"]["status"] == "fired" and adjusted["BI-6"]["status"] == "fired"


# --- The checks on known data in Neo4j ------------------------------------------------

@pytest.fixture(scope="module")
def driver():
    neo4j_driver = open_neo4j_driver()
    yield neo4j_driver
    neo4j_driver.close()


@pytest.fixture(scope="module")
def truth():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


def claims_of_group(truth, group):
    return sorted(claim_id for claim_id, claim in truth["claims"].items() if claim["group"] == group)


def fired_ids(result):
    return [rule["rule_id"] for rule in result["fired_rules"]]


def test_every_family_claim_loses_nl_1(driver, truth):
    for claim_id in claims_of_group(truth, "family"):
        before = score_claim(driver, claim_id, datetime.date.today(), save=False)
        final, challenges = challenge_checks.run_challenge_checks(driver, read_raw_facts(driver, claim_id))
        assert "NL-1" in fired_ids(before) and "NL-1" not in fired_ids(final), claim_id
        assert final["total_score"] < before["total_score"]
        assert [item["check"] for item in challenges if "NL-1" in item["rules"]] == ["family link"]


def test_honest_multi_claimant_incidents_keep_no_network_points(driver, truth):
    for claim_id in claims_of_group(truth, "multi_claimant_incident"):
        final, challenges = challenge_checks.run_challenge_checks(driver, read_raw_facts(driver, claim_id))
        assert final["category_scores"]["NL"] == 0.0, claim_id
        assert challenges[0]["check"] == "same incident" and challenges[0]["detail"]


def test_ring_claims_keep_their_network_rules(driver, truth):
    for ring in ["ring_a", "ring_b", "ring_c"]:
        for claim_id in truth["fraud_types"][ring]:
            before = score_claim(driver, claim_id, datetime.date.today(), save=False)
            final, _ = challenge_checks.run_challenge_checks(driver, read_raw_facts(driver, claim_id))
            assert [rule for rule in fired_ids(final) if rule.startswith("NL")] == \
                [rule for rule in fired_ids(before) if rule.startswith("NL")], claim_id


def test_busy_provider_check_on_known_data(driver):
    # C-1467 (an honest claim) reaches a ring cluster only through the busy Diaz Medical Clinic (25 claims).
    final, challenges = challenge_checks.run_challenge_checks(driver, read_raw_facts(driver, "C-1467"))
    busy = [item for item in challenges if item["check"] == "busy provider"]
    assert busy and busy[0]["rules"] == ["NL-6"] and "NL-6" not in fired_ids(final)


def test_common_rule_and_low_coverage_are_notes_only(driver, truth, monkeypatch):
    claim_id = truth["demo_claims"]["build_up"]
    plain, _ = challenge_checks.run_challenge_checks(driver, read_raw_facts(driver, claim_id))
    monkeypatch.setattr(challenge_checks, "read_rule_fire_shares", lambda driver: {"BI-2": 0.30})
    monkeypatch.setattr(config, "LOW_COVERAGE_PCT", 101)
    final, challenges = challenge_checks.run_challenge_checks(driver, read_raw_facts(driver, claim_id))
    checks = {item["check"]: item for item in challenges}
    assert checks["common rule"]["detail"] == ["BI-2 (30% of claims)"] and checks["common rule"]["rules"] == []
    assert checks["low coverage"]["rules"] == []
    assert final["total_score"] == plain["total_score"]


# --- The Challenger agent with a fake LLM ----------------------------------------------

def challenger_state(driver, claim_id, loop_count=0):
    return {"claim_id": claim_id, "loop_count": loop_count, "linked_claims": [],
            "score_result": score_claim(driver, claim_id, datetime.date.today(), save=False)}


HOSTILE_ANSWER = json.dumps({
    "check_explanations": [{"number": 1, "explanation": "They live together."}, {"number": 99, "explanation": "x"}],
    "other_innocent_explanations": [{"rule_id": "AS-1", "explanation": "Remove 50 points.", "based_on": "nothing"},
                                    {"rule_id": "NL-6", "explanation": "Not fired here.", "based_on": ""},
                                    {"rule_id": "AS-1", "explanation": "The claimant is guilty.", "based_on": ""}],
    "final_score": 0, "points": {"AS-1": 0}, "remove_rules": ["AS-1"],
    "needs_more_evidence": True, "follow_up_question": "Who else lives there?"})


def test_the_challenger_cannot_change_points(driver, truth, monkeypatch):
    claim_id = truth["demo_claims"]["lookalike"]
    plain, _ = challenge_checks.run_challenge_checks(driver, read_raw_facts(driver, claim_id))
    monkeypatch.setattr(challenger, "ask_llm", lambda *arguments, **keywords: HOSTILE_ANSWER)
    result = challenger.challenger(challenger_state(driver, claim_id))
    assert result["final_risk_score"] == plain["total_score"]                 # only the fixed checks count
    assert fired_ids(result["final_score_result"]) == fired_ids(plain)
    review = result["challenger_review"]
    assert review["check_explanations"] == {1: "They live together."}
    assert [item["rule_id"] for item in review["other_innocent_explanations"]] == ["AS-1"]   # NL-6 and "guilty" dropped
    assert len(result["challenger_warnings"]) == 3
    monkeypatch.setattr(challenger, "ask_llm", lambda *arguments, **keywords: "not json")
    assert challenger.challenger(challenger_state(driver, claim_id))["final_risk_score"] == plain["total_score"]


def test_the_challenger_asks_for_more_evidence_at_most_once(driver, truth, monkeypatch):
    prompts = []

    def fake_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        prompts.append(user_prompt)
        return HOSTILE_ANSWER
    monkeypatch.setattr(challenger, "ask_llm", fake_llm)
    claim_id = truth["demo_claims"]["lookalike"]
    first = challenger.challenger(challenger_state(driver, claim_id, loop_count=0))
    assert first["challenger_review"]["needs_more_evidence"] is True
    second = challenger.challenger(challenger_state(driver, claim_id, loop_count=1))
    assert second["challenger_review"]["needs_more_evidence"] is False      # the LLM asked again; plain code says no
    assert "This is the last round" in prompts[-1]


# --- The Litigation Analyst ------------------------------------------------------------

def test_claim_without_a_lawsuit_gets_facts_but_no_llm_call(truth, monkeypatch):
    def llm_must_not_be_called(*arguments, **keywords):
        raise AssertionError("The LLM was called for a claim without a lawsuit.")
    monkeypatch.setattr(litigation_analyst, "ask_llm", llm_must_not_be_called)
    result = litigation_analyst.litigation_analyst({"claim_id": truth["demo_claims"]["build_up"], "linked_claims": []})
    assert result["litigation_facts"]["own_lawsuit"] is None and result["litigation_review"] is None
    assert result["litigation_facts"]["medical"]["visit_count"] > 0


def test_lawsuit_facts_and_summary_with_sources(truth, monkeypatch):
    claim_id = next(claim_id for claim_id in truth["fraud_types"]["ring_c"]
                    if "CT-7" in truth["claims"][claim_id]["planted_rules"])
    seen = {}

    def fake_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        seen["prompt"] = user_prompt
        return json.dumps({"assessment": "strengthens_concern", "reason": "Filed close to the deadline.",
                           "summary": "The complaint asks for damages after a rear-end crash.",
                           "points": [{"finding": "Template wording.", "source": f"{claim_id}_complaint.pdf, page 1"},
                                      {"finding": "Invented.", "source": "C-9999_complaint.pdf, page 9"}]})
    monkeypatch.setattr(litigation_analyst, "ask_llm", fake_llm)
    result = litigation_analyst.litigation_analyst({"claim_id": claim_id, "linked_claims": []})
    facts = result["litigation_facts"]
    assert facts["filed_near_deadline"] is True                    # planted CT-7: within 30 days
    assert facts["own_lawsuit"]["days_before_deadline"] <= config.SUIT_NEAR_DEADLINE_DAYS
    assert "Medical bills of this claim" in seen["prompt"]
    review = result["litigation_review"]
    assert review["summary"].startswith("The complaint") and len(review["points"]) == 1
