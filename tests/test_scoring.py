"""V7 tests: each rule on a small made-up fact set, the score math, and repeatability.

The rule tests need no database: the facts are a plain dict, built below. One honest claim
(BASE) fires nothing. Each case changes one thing and says what the rule must answer.
The last tests use Neo4j and the real v2 data, with a fake LLM.
"""

import copy
import datetime
import json

import pytest

from src import config
from src.agents import risk_scoring
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.scoring.engine import band_for, run_rules, score_claim, score_facts, score_rule_results
from src.scoring.rules import RULE_CHECKS
from src.scoring.rules_catalog import RULES

LOSS = datetime.date(2024, 3, 1)


def day(offset):
    return LOSS + datetime.timedelta(days=offset)


HARMLESS = {"injury_crash_fit": "Strong", "treatment_growth": "Normal", "objective_support": "Strong",
            "pre_existing_condition": "None", "occurrence_support": "Confirmed", "damage_crash_fit": "Strong",
            "account_stability": "Stable", "occupant_presence": "Verified", "occupants_listed": 3,
            "duplicate_billing": "None", "labor_hours_plausibility": "Plausible", "prior_damage_evidence": "None",
            "known_loss_evidence": "Weak", "driver_status": "Listed"}


def finding(code, value):
    return {"finding_id": f"C-TEST-medical_records-p1-{code}", "feature": code, "value": value, "confidence": "High",
            "document_id": "C-TEST-medical_records", "page_number": 1, "quote": f"A quote about {code}."}


BASE = {
    "claim_id": "C-TEST", "loss_date": LOSS, "reported_date": day(5), "attorney_retained_date": day(20),
    "repair_estimate_amount": 4000.0,
    "policy": {"policy_id": "P-1", "effective_date": datetime.date(2023, 6, 1),
               "expiration_date": datetime.date(2024, 6, 1), "customer_since": datetime.date(2020, 1, 1),
               "last_coverage_increase_date": None, "lapse_start": None, "lapse_end": None},
    "incident_id": "I-1", "incident_claimant_count": 2,
    "visit_dates": [day(3 * number) for number in range(10)],               # 10 visits in the first 30 days
    "payments": [{"payment_id": "PAY-1", "payment_date": day(20), "amount": 4400.0, "payment_type": "repair"},
                 {"payment_id": "PAY-2", "payment_date": day(50), "amount": 2000.0, "payment_type": "medical"}],
    "reserve_events": [{"event_id": "RE-1", "event_date": day(5), "reserve_total": 8000.0},
                       {"event_id": "RE-2", "event_date": day(60), "reserve_total": 9000.0}],
    "lawsuits": [{"lawsuit_id": "LS-1", "filed_date": day(300), "limitation_deadline": datetime.date(2026, 3, 1)}],
    "document_loss_dates": [{"document_id": "C-TEST-police_report", "loss_date_in_pdf": LOSS, "page_number": 1,
                             "conflict": False}],
    "findings": {code: finding(code, value) for code, value in HARMLESS.items()},
    "weak_findings": [],
    # Network facts (V8): no strong link, no other claim, no copy. The claim is alone in its group.
    "strong_links": [], "repeat_claims": [], "copied_story": [], "has_story_text": True,
    "cluster_claim_ids": ["C-TEST"],
}


def facts_with(change):
    """A copy of BASE with one change. `change` is a function that edits the copy."""
    facts = copy.deepcopy(BASE)
    change(facts)
    return facts


def rated(code, value):
    def change(facts):
        facts["findings"][code] = finding(code, value)
    return change


def removed(code):
    def change(facts):
        del facts["findings"][code]
    return change


def set_value(key, value):
    def change(facts):
        facts[key] = value
    return change


def set_policy(key, value):
    def change(facts):
        facts["policy"][key] = value
    return change


def payments_on(offsets, payment_type="medical", amount=100.0):
    def change(facts):
        facts["payments"] = [{"payment_id": f"PAY-{offset}", "payment_date": day(offset), "amount": amount,
                              "payment_type": payment_type} for offset in offsets]
    return change


def reserves(*events):
    def change(facts):
        facts["reserve_events"] = [{"event_id": f"RE-{offset}", "event_date": day(offset), "reserve_total": total}
                                   for offset, total in events]
    return change


def filed_days_before_deadline(days):
    def change(facts):
        deadline = facts["lawsuits"][0]["limitation_deadline"]
        facts["lawsuits"][0]["filed_date"] = deadline - datetime.timedelta(days=days)
    return change


def lapse(start_offset, end_offset):
    def change(facts):
        facts["policy"]["lapse_start"] = day(start_offset)
        facts["policy"]["lapse_end"] = day(end_offset)
    return change


def document_conflict(facts):
    facts["document_loss_dates"][0].update({"loss_date_in_pdf": day(-3), "conflict": True})


def two_documents_agree(facts):
    facts["document_loss_dates"].append({"document_id": "C-TEST-fnol", "loss_date_in_pdf": LOSS, "page_number": 1,
                                         "conflict": False})


def strong_links(kind, count, filed_days_apart=None):
    def change(facts):
        facts["strong_links"] = []
        for number in range(count):
            link = {"linked_claim_id": f"C-OTHER-{number}", "kind": kind, "shared_value": "shared",
                    "source_filed_date": None, "linked_filed_date": None}
            if filed_days_apart is not None:
                link["source_filed_date"] = day(300)
                link["linked_filed_date"] = day(300 + filed_days_apart)
            facts["strong_links"].append(link)
    return change


def repeat_claims(*loss_offsets):
    def change(facts):
        facts["repeat_claims"] = [{"claim_id": f"C-OTHER-{offset}", "loss_date": day(offset)}
                                  for offset in loss_offsets]
    return change


def copied_story(facts):
    facts["copied_story"] = [{"document_id": "C-TEST-fnol", "page_number": 1, "other_claim_id": "C-OTHER",
                              "other_document_id": "C-OTHER-fnol", "other_page_number": 1, "score": 0.991}]


def cluster_of(size):
    def change(facts):
        facts["cluster_claim_ids"] = ["C-TEST"] + [f"C-OTHER-{number}" for number in range(size - 1)]
    return change


def no_document_date(facts):
    facts["document_loss_dates"][0].update({"loss_date_in_pdf": None, "page_number": None})


FIRED, QUIET, MISSING = "fired", "not_fired", "not_evaluated"

# (rule, what changes, expected answer). Each rule has a "fires" case and a "quiet" case, and a
# "missing" case when an input can be missing. Thresholds are tested on both sides.
CASES = [
    ("BI-1", rated("injury_crash_fit", "Inconsistent"), FIRED),
    ("BI-1", rated("injury_crash_fit", "Unclear"), QUIET),
    ("BI-1", removed("injury_crash_fit"), MISSING),
    ("BI-2", rated("treatment_growth", "Extreme"), FIRED),
    ("BI-2", rated("treatment_growth", "Elevated"), QUIET),
    ("BI-2", removed("treatment_growth"), MISSING),
    ("BI-3", rated("objective_support", "Contradicted"), FIRED),
    ("BI-3", rated("objective_support", "Partial"), QUIET),
    ("BI-3", removed("objective_support"), MISSING),
    ("BI-4", rated("pre_existing_condition", "Material"), FIRED),
    ("BI-4", rated("pre_existing_condition", "Minor"), QUIET),
    ("BI-4", removed("pre_existing_condition"), MISSING),
    ("BI-5", set_value("attorney_retained_date", day(-1)), FIRED),           # before the first visit (day 0)
    ("BI-5", set_value("attorney_retained_date", day(0)), QUIET),            # same day is not before
    ("BI-5", set_value("attorney_retained_date", None), MISSING),
    ("BI-5", set_value("visit_dates", []), MISSING),
    ("BI-6", set_value("visit_dates", [day(2 * number) for number in range(13)]), FIRED),   # 13 visits by day 24
    ("BI-6", set_value("visit_dates", [day(2 * number) for number in range(12)]), QUIET),   # 12 is not "more than 12"
    ("BI-6", set_value("visit_dates", [day(2 * number) for number in range(12)] + [day(31)]), QUIET),  # day 31 is late
    ("AS-1", rated("occurrence_support", "Uncorroborated"), FIRED),
    ("AS-1", rated("occurrence_support", "Contradicted"), QUIET),            # that is AS-2, not AS-1
    ("AS-1", removed("occurrence_support"), MISSING),
    ("AS-2", rated("occurrence_support", "Suspected staged"), FIRED),
    ("AS-2", rated("occurrence_support", "Uncorroborated"), QUIET),
    ("AS-2", removed("occurrence_support"), MISSING),
    ("AS-3", rated("damage_crash_fit", "Inconsistent"), FIRED),
    ("AS-3", rated("damage_crash_fit", "Unclear"), QUIET),
    ("AS-3", removed("damage_crash_fit"), MISSING),
    ("AS-4", rated("account_stability", "Materially changed"), FIRED),
    ("AS-4", rated("account_stability", "Clarified"), QUIET),
    ("AS-4", removed("account_stability"), MISSING),
    ("AS-5", rated("occupant_presence", "Added later"), FIRED),
    ("AS-5", rated("occupant_presence", "Unclear"), QUIET),
    ("AS-5", removed("occupant_presence"), MISSING),
    ("AS-6", rated("occupants_listed", 1), FIRED),                           # 2 claimants, 1 occupant
    ("AS-6", rated("occupants_listed", 2), QUIET),                           # 2 claimants, 2 occupants
    ("AS-6", removed("occupants_listed"), MISSING),
    ("AS-6", set_value("incident_claimant_count", None), MISSING),
    ("AS-7", document_conflict, FIRED),
    ("AS-7", two_documents_agree, QUIET),
    ("AS-7", no_document_date, MISSING),
    ("BF-1", reserves((5, 8000.0), (30, 12000.01)), FIRED),                   # +50.0001% in 25 days
    ("BF-1", reserves((5, 8000.0), (30, 12000.0)), QUIET),                    # exactly +50% is not "more than"
    ("BF-1", reserves((5, 8000.0), (36, 16000.0)), QUIET),                    # +100%, but after 31 days
    ("BF-1", reserves(), MISSING),
    ("BF-2", reserves((5, 4000.0)), FIRED),                                   # paid 6400 = 1.6 x 4000
    ("BF-2", reserves((5, 4000.0), (60, 4300.0)), QUIET),                     # the latest reserve counts: 6400 < 6450
    ("BF-2", reserves(), MISSING),
    ("BF-3", payments_on([10, 17, 24]), FIRED),                               # 3 payments within 14 days
    ("BF-3", payments_on([10, 17, 25]), QUIET),                               # within 15 days
    ("BF-4", payments_on([20], "repair", 6000.0), FIRED),                     # exactly 1.5 x 4000
    ("BF-4", payments_on([20], "repair", 5999.99), QUIET),
    ("BF-4", set_value("repair_estimate_amount", None), MISSING),
    ("BF-5", rated("duplicate_billing", "Confirmed"), FIRED),
    ("BF-5", rated("duplicate_billing", "Possible"), QUIET),
    ("BF-5", removed("duplicate_billing"), MISSING),
    ("BF-6", rated("labor_hours_plausibility", "Excessive"), FIRED),
    ("BF-6", rated("labor_hours_plausibility", "Elevated"), QUIET),
    ("BF-6", removed("labor_hours_plausibility"), MISSING),
    ("CT-1", set_policy("customer_since", day(-29)), FIRED),
    ("CT-1", set_policy("customer_since", day(-30)), QUIET),                  # 30 days is not "under 30"
    ("CT-1", set_policy("customer_since", day(10)), FIRED),                   # customer only after the loss
    ("CT-1", set_policy("customer_since", None), MISSING),
    ("CT-2", set_policy("last_coverage_increase_date", day(-30)), FIRED),
    ("CT-2", set_policy("last_coverage_increase_date", day(-31)), QUIET),
    ("CT-2", set_policy("last_coverage_increase_date", day(5)), QUIET),       # the increase came after the loss
    ("CT-2", set_value("policy", None), MISSING),
    ("CT-3", set_policy("effective_date", day(1)), FIRED),                    # the policy starts after the loss
    ("CT-3", set_policy("expiration_date", day(-1)), FIRED),                  # the policy ended before the loss
    ("CT-3", lapse(-5, 5), FIRED),                                            # the loss is inside a lapse
    ("CT-3", lapse(-400, -380), QUIET),                                       # an old lapse
    ("CT-3", set_value("policy", None), MISSING),
    ("CT-4", set_value("reported_date", day(31)), FIRED),
    ("CT-4", set_value("reported_date", day(30)), QUIET),
    ("CT-5", rated("prior_damage_evidence", "Documented"), FIRED),
    ("CT-5", rated("known_loss_evidence", "Strong"), FIRED),
    ("CT-5", rated("prior_damage_evidence", "Possible"), QUIET),
    ("CT-5", removed("prior_damage_evidence"), QUIET),                        # known_loss_evidence is still there
    ("CT-6", rated("driver_status", "Excluded"), FIRED),
    ("CT-6", rated("driver_status", "Household"), QUIET),
    ("CT-6", removed("driver_status"), MISSING),
    ("CT-7", filed_days_before_deadline(30), FIRED),
    ("CT-7", filed_days_before_deadline(31), QUIET),
    ("CT-7", filed_days_before_deadline(-5), QUIET),                          # filed after the deadline
    ("CT-7", set_value("lawsuits", []), MISSING),
    ("NL-1", strong_links("phone", 1), FIRED),
    ("NL-1", strong_links("address", 1), FIRED),
    ("NL-1", strong_links("clinic_and_attorney", 1), QUIET),                  # not a phone or address
    ("NL-2", repeat_claims(-400, 700), FIRED),                               # 2 other claims within 1095 days
    ("NL-2", repeat_claims(-400), QUIET),                                    # only 1
    ("NL-2", repeat_claims(-400, 1096), QUIET),                              # the second is too far away
    ("NL-3", strong_links("clinic_and_attorney", 5), FIRED),
    ("NL-3", strong_links("clinic_and_attorney", 4), QUIET),
    ("NL-3", set_value("attorney_retained_date", None), MISSING),
    ("NL-4", copied_story, FIRED),
    ("NL-4", set_value("copied_story", []), QUIET),
    ("NL-4", set_value("has_story_text", False), MISSING),
    ("NL-5", strong_links("firm_and_expert", 3, filed_days_apart=365), FIRED),
    ("NL-5", strong_links("firm_and_expert", 3, filed_days_apart=366), QUIET),   # outside 12 months
    ("NL-5", strong_links("firm_and_expert", 2, filed_days_apart=10), QUIET),
    ("NL-5", set_value("lawsuits", []), MISSING),
    ("NL-6", cluster_of(8), FIRED),
    ("NL-6", cluster_of(7), QUIET),
]


def both_prior_and_known_missing(facts):
    del facts["findings"]["prior_damage_evidence"]
    del facts["findings"]["known_loss_evidence"]


CASES.append(("CT-5", both_prior_and_known_missing, MISSING))


def test_the_honest_base_claim_fires_no_rule():
    results = run_rules(BASE)
    for rule in RULES:
        assert results[rule.rule_id]["status"] == QUIET, rule.rule_id


# parametrize: pytest runs the test once for each case in the list, and names each run.
@pytest.mark.parametrize("rule_id, change, expected", CASES)
def test_each_rule_on_made_up_facts(rule_id, change, expected):
    result = RULE_CHECKS[rule_id](facts_with(change))
    assert result["status"] == expected
    assert result["proof"]                      # every answer carries its proof (or what is missing)


def test_every_rule_has_a_fires_and_a_quiet_case():
    for rule in RULES:
        answers = {expected for rule_id, _, expected in CASES if rule_id == rule.rule_id}
        assert {FIRED, QUIET} <= answers, rule.rule_id


def test_a_notes_rule_names_the_finding_as_proof():
    proof = RULE_CHECKS["BI-1"](facts_with(rated("injury_crash_fit", "Inconsistent")))["proof"]
    assert proof["findings"][0]["finding_id"] == "C-TEST-medical_records-p1-injury_crash_fit"
    assert proof["findings"][0]["page_number"] == 1 and proof["findings"][0]["quote"]


def test_score_math_on_a_worked_example():
    # BI-1 (15 of 57 BI points) and CT-3 (20 of 80 CT points) fire. Worked out by hand:
    # BI = 15 / 57 x 100 = 26.32; CT = 20 / 80 x 100 = 25.0
    # total = 0.25 x 26.32 + 0.15 x 25.0 = 6.58 + 3.75 = 10.33 -> 10.3, band Medium
    # coverage = every input exists = 352 / 352 = 100%
    facts = facts_with(rated("injury_crash_fit", "Inconsistent"))
    facts["policy"]["effective_date"] = day(1)
    result = score_facts(facts)
    assert result["category_scores"] == {"BI": 26.3, "AS": 0.0, "BF": 0.0, "CT": 25.0, "NL": 0.0}
    assert result["total_score"] == 10.3 and result["band"] == "Medium"
    assert result["coverage_pct"] == 100.0
    shares = {rule["rule_id"]: rule["points_in_total"] for rule in result["fired_rules"]}
    assert shares == {"BI-1": 6.58, "CT-3": 3.75}                 # the shares add up to the total


def test_a_missing_input_lowers_coverage_but_not_the_score():
    with_input = score_facts(BASE)
    without_input = score_facts(facts_with(removed("injury_crash_fit")))
    assert without_input["total_score"] == with_input["total_score"] == 0.0
    assert without_input["coverage_pct"] == round((352 - 15) / 352 * 100, 1)


def test_band_limits():
    assert [band_for(score)[0] for score in (0, 9.9, 10, 19.9, 20, 29.9, 30, 100)] == \
        ["Low", "Low", "Medium", "Medium", "High", "High", "Very High", "Very High"]


def test_same_input_same_score():
    first = score_rule_results(run_rules(copy.deepcopy(BASE)))
    second = score_rule_results(run_rules(copy.deepcopy(BASE)))
    assert first == second


# --- With Neo4j and the real v2 data ---------------------------------------------------

@pytest.fixture(scope="module")
def truth():
    if not config.GROUND_TRUTH_FILE.exists():
        pytest.skip("No v2 data. Run: python main.py generate-data --tables")
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


def test_a_real_claim_scored_twice_gives_the_same_score_and_one_snapshot(truth):
    claim_id = truth["demo_claims"]["build_up"]
    today = datetime.date.today()
    driver = open_neo4j_driver()
    try:
        first = score_claim(driver, claim_id, today)
        second = score_claim(driver, claim_id, today)
        records, _, _ = driver.execute_query(queries.SNAPSHOTS_OF_CLAIM, claim_id=claim_id)
    finally:
        driver.close()
    assert first == second
    todays = [record for record in records if record["snapshot_id"] == f"{claim_id}-{today.isoformat()}"]
    assert len(todays) == 1                                        # scoring again replaces the snapshot
    assert todays[0]["total_score"] == first["total_score"]
    assert todays[0]["fired_rule_ids"] == [rule["rule_id"] for rule in first["fired_rules"]]


def test_the_agent_explains_each_fired_rule_with_points_and_proof(truth, monkeypatch):
    monkeypatch.setattr(risk_scoring, "ask_llm",
                        lambda *arguments, **keywords: "Medical build-up drives this score. Check the visits.")
    result = risk_scoring.risk_scoring({"claim_id": truth["demo_claims"]["build_up"]})
    explanation = result["risk_explanation"]
    assert explanation.startswith("Medical build-up drives this score.")
    assert result["score_result"]["fired_rules"]
    for rule in result["score_result"]["fired_rules"]:
        assert f"{rule['rule_id']:<5} {rule['name']}" in explanation and f"{rule['points']:>3} pts" in explanation
    assert "proof: " in explanation and "page" in explanation
    assert result["risk_summary"] == "Medical build-up drives this score. Check the visits."


def test_a_summary_with_forbidden_words_is_replaced(truth, monkeypatch):
    monkeypatch.setattr(risk_scoring, "ask_llm", lambda *arguments, **keywords: "The claimant is guilty.")
    result = risk_scoring.risk_scoring({"claim_id": truth["demo_claims"]["build_up"]})
    assert "guilty" not in result["risk_explanation"] and result["risk_warnings"]
