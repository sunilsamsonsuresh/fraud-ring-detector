"""Tests of src/scoring/rules_findings.py (new system).

The first tests use made-up findings and need no Neo4j (expected answers worked out by hand).
The last test uses the real graph and compares every rule with the old check on all 500 claims.
"""

import pytest

from src.scoring import rules_findings
from src.scoring.rules_findings import FINDING_RULE_CHECKS

RULE_IDS = [
    "BI-1",
    "BI-2",
    "BI-3",
    "BI-4",
    "AS-1",
    "AS-2",
    "AS-3",
    "AS-4",
    "AS-5",
    "AS-6",
    "BF-5",
    "BF-6",
    "CT-5",
    "CT-6",
]


def made_up(feature, value):
    return {
        "finding_id": f"D-p1-{feature}",
        "feature": feature,
        "value": value,
        "confidence": "High",
        "document_id": "D",
        "page_number": 3,
        "quote": "quote",
    }


def facts_of(*pairs):
    return {"findings": {feature: made_up(feature, value) for feature, value in pairs}}


def test_the_group_has_the_14_rules():
    assert sorted(FINDING_RULE_CHECKS) == sorted(RULE_IDS)


@pytest.mark.parametrize(
    "rule_id, feature, value, status",
    [
        ("BI-1", "injury_crash_fit", "Inconsistent", "fired"),
        ("BI-1", "injury_crash_fit", "Unclear", "not_fired"),
        ("BI-2", "treatment_growth", "Disproportionate", "fired"),
        ("BI-2", "treatment_growth", "Extreme", "fired"),
        ("BI-2", "treatment_growth", "Elevated", "not_fired"),
        ("BI-3", "objective_support", "Contradicted", "fired"),
        ("BI-3", "objective_support", "Partial", "not_fired"),
        ("BI-4", "pre_existing_condition", "Material", "fired"),
        ("BI-4", "pre_existing_condition", "Minor", "not_fired"),
        ("AS-1", "occurrence_support", "Uncorroborated", "fired"),
        ("AS-1", "occurrence_support", "Contradicted", "not_fired"),
        ("AS-2", "occurrence_support", "Suspected staged", "fired"),
        ("AS-2", "occurrence_support", "Uncorroborated", "not_fired"),
        ("AS-3", "damage_crash_fit", "Inconsistent", "fired"),
        ("AS-4", "account_stability", "Materially changed", "fired"),
        ("AS-4", "account_stability", "Clarified", "not_fired"),
        ("AS-5", "occupant_presence", "Added later", "fired"),
        ("AS-5", "occupant_presence", "Unclear", "not_fired"),
        ("BF-5", "duplicate_billing", "Confirmed", "fired"),
        ("BF-5", "duplicate_billing", "Possible", "not_fired"),
        ("BF-6", "labor_hours_plausibility", "Excessive", "fired"),
        ("BF-6", "labor_hours_plausibility", "Elevated", "not_fired"),
        ("CT-6", "driver_status", "Excluded", "fired"),
        ("CT-6", "driver_status", "Household", "not_fired"),
    ],
)
def test_one_feature_rules(rule_id, feature, value, status):
    assert FINDING_RULE_CHECKS[rule_id](facts_of((feature, value)))["status"] == status


def test_a_missing_finding_is_not_evaluated():
    for rule_id in RULE_IDS:
        facts = {"findings": {}, "incident_claimant_count": 2, "incident_id": "I-1"}
        assert FINDING_RULE_CHECKS[rule_id](facts)["status"] == "not_evaluated"


def test_ct_5_uses_two_features():
    check = FINDING_RULE_CHECKS["CT-5"]
    assert check(facts_of(("prior_damage_evidence", "Documented")))["status"] == "fired"
    assert check(facts_of(("known_loss_evidence", "Strong")))["status"] == "fired"
    assert check(facts_of(("known_loss_evidence", "Moderate")))["status"] == "not_fired"
    assert (
        check(
            facts_of(
                ("prior_damage_evidence", "Possible"), ("known_loss_evidence", "Weak")
            )
        )["status"]
        == "not_fired"
    )
    both = check(
        facts_of(("prior_damage_evidence", "None"), ("known_loss_evidence", "Strong"))
    )
    assert both["status"] == "fired" and len(both["proof"]["findings"]) == 2


def as_6_facts(listed, claimants):
    facts = facts_of(("occupants_listed", listed))
    facts.update({"incident_id": "I-1", "incident_claimant_count": claimants})
    return facts


def test_as_6_compares_claimants_with_occupants():
    check = FINDING_RULE_CHECKS["AS-6"]
    assert check(as_6_facts(2, 3))["status"] == "fired"  # 3 claimants, 2 seats listed
    assert check(as_6_facts(2, 2))["status"] == "not_fired"  # equal is fine
    assert check(as_6_facts(3, 1))["status"] == "not_fired"
    assert check(as_6_facts(2, 3))["proof"]["claimants_in_incident"] == 3


def test_as_6_is_not_evaluated_without_the_number_or_the_incident():
    check = FINDING_RULE_CHECKS["AS-6"]
    assert (
        check({"findings": {}, "incident_claimant_count": 3, "incident_id": "I-1"})[
            "status"
        ]
        == "not_evaluated"
    )
    assert check(as_6_facts(2, None))["status"] == "not_evaluated"


def test_the_proof_names_document_page_and_quote():
    proof = rules_findings.check_bi_2(facts_of(("treatment_growth", "Extreme")))[
        "proof"
    ]["findings"][0]
    assert (proof["document_id"], proof["page_number"], proof["quote"]) == (
        "D",
        3,
        "quote",
    )


# --- With the real graph, and the old checks as reference ---
