"""Tests of src/scoring/rules_network.py (new system).

Most tests use made-up facts, so they need no Neo4j. Some tests use real claims (Neo4j must be running).
"""

import datetime

from src import config
from src.scoring.rules_catalog import RULES_BY_ID
from src.scoring.rules_network import (
    NETWORK_RULE_CHECKS,
    check_nl_1,
    check_nl_2,
    check_nl_4,
    check_nl_5,
    check_nl_6,
    days_for_months,
)

LOSS = datetime.date(2025, 3, 1)
FILED = datetime.date(2025, 9, 1)


def link(claim_number, kind, **extra):
    return {
        "linked_claim_id": f"C-{2000 + claim_number}",
        "kind": kind,
        "shared_value": "shared",
        **extra,
    }


def firm_link(claim_number, days_apart):
    return link(
        claim_number,
        "firm_and_expert",
        source_filed_date=FILED,
        linked_filed_date=FILED + datetime.timedelta(days=days_apart),
    )


def repeat_claim(claim_number, days_from_loss):
    return {
        "claim_id": f"C-{4000 + claim_number}",
        "loss_date": LOSS + datetime.timedelta(days=days_from_loss),
    }


def facts_with(**changes):
    facts = {
        "loss_date": LOSS,
        "direct_links": [],
        "repeat_claims": [],
        "cluster_claim_ids": ["C-1000"],
        "lawsuits": [
            {"lawsuit_id": "LS-1", "filed_date": FILED, "limitation_deadline": FILED}
        ],
    }
    facts.update(changes)
    return facts


def status(result):
    return result["status"]


def test_days_for_months_uses_a_365_day_year():
    assert days_for_months(12) == 365
    assert days_for_months(36) == 1095


# --- NL-1: shared phone or address ---


def test_nl_1_fires_for_a_phone_or_an_address_link_and_ignores_other_kinds():
    assert status(check_nl_1(facts_with(direct_links=[link(1, "phone")]))) == "fired"
    assert status(check_nl_1(facts_with(direct_links=[link(1, "address")]))) == "fired"
    other_kinds = [link(1, "clinic_and_attorney"), link(2, "firm_and_expert")]
    assert status(check_nl_1(facts_with(direct_links=other_kinds))) == "not_fired"
    assert status(check_nl_1(facts_with(direct_links=[]))) == "not_fired"


def test_nl_1_proof_names_the_linked_claims_without_repeats_and_cuts_at_10():
    result = check_nl_1(facts_with(direct_links=[link(1, "phone"), link(1, "phone")]))
    assert result["proof"]["links"] == ["C-2001 (phone: shared)"]
    many = [link(number, "address") for number in range(15)]
    assert len(check_nl_1(facts_with(direct_links=many))["proof"]["links"]) == 10


# --- NL-2: repeat claimant (2 or more other claims within 36 months) ---


def test_nl_2_needs_two_other_claims():
    assert (
        status(check_nl_2(facts_with(repeat_claims=[repeat_claim(1, 100)])))
        == "not_fired"
    )
    assert (
        status(
            check_nl_2(
                facts_with(repeat_claims=[repeat_claim(1, 100), repeat_claim(2, -100)])
            )
        )
        == "fired"
    )


def test_nl_2_counts_day_1095_but_not_day_1096_before_or_after():
    for days in [1095, -1095]:
        assert (
            status(
                check_nl_2(
                    facts_with(
                        repeat_claims=[repeat_claim(1, days), repeat_claim(2, days)]
                    )
                )
            )
            == "fired"
        )
    for days in [1096, -1096]:
        assert (
            status(
                check_nl_2(
                    facts_with(
                        repeat_claims=[repeat_claim(1, days), repeat_claim(2, days)]
                    )
                )
            )
            == "not_fired"
        )


def test_nl_2_with_no_other_claims_does_not_fire():
    assert status(check_nl_2(facts_with(repeat_claims=[]))) == "not_fired"


# --- NL-5: same law firm and same expert (3 or more claims, suits filed within 12 months) ---


def test_nl_5_needs_three_claims_within_365_days():
    assert (
        status(
            check_nl_5(facts_with(direct_links=[firm_link(1, 10), firm_link(2, -10)]))
        )
        == "not_fired"
    )
    result = check_nl_5(
        facts_with(
            direct_links=[firm_link(1, 10), firm_link(2, -10), firm_link(3, 365)]
        )
    )
    assert status(result) == "fired"
    assert result["proof"] == {
        "lawsuits_within_window": 3,
        "linked_claims": ["C-2001", "C-2002", "C-2003"],
    }


def test_nl_5_ignores_a_suit_filed_more_than_365_days_apart_and_other_kinds():
    links = [
        firm_link(1, 10),
        firm_link(2, 20),
        firm_link(3, 366),
        firm_link(4, -366),
        link(5, "phone"),
    ]
    assert status(check_nl_5(facts_with(direct_links=links))) == "not_fired"


def test_nl_5_counts_a_claim_once_and_is_not_evaluated_without_a_lawsuit():
    twice = [firm_link(1, 10), firm_link(1, 20), firm_link(2, 30)]
    assert (
        check_nl_5(facts_with(direct_links=twice))["proof"]["lawsuits_within_window"]
        == 2
    )
    assert (
        status(check_nl_5(facts_with(lawsuits=[], direct_links=[firm_link(1, 1)] * 5)))
        == "not_evaluated"
    )


# --- NL-6: large linked cluster (8 or more claims, the claim included) ---


def test_nl_6_needs_8_claims_and_counts_the_claim_itself():
    seven = [f"C-{1000 + number}" for number in range(7)]
    eight = [f"C-{1000 + number}" for number in range(8)]
    assert status(check_nl_6(facts_with(cluster_claim_ids=seven))) == "not_fired"
    result = check_nl_6(facts_with(cluster_claim_ids=eight))
    assert status(result) == "fired"
    assert result["proof"]["claims_in_group"] == 8


def test_nl_6_cuts_the_list_in_the_proof_at_10_but_counts_all():
    result = check_nl_6(
        facts_with(cluster_claim_ids=[f"C-{1000 + number}" for number in range(15)])
    )
    assert result["proof"]["claims_in_group"] == 15
    assert len(result["proof"]["claims"]) == 10


def test_the_thresholds_are_in_config(monkeypatch):
    monkeypatch.setattr(config, "REPEAT_CLAIM_OTHER_CLAIMS", 1)
    assert (
        status(check_nl_2(facts_with(repeat_claims=[repeat_claim(1, 100)]))) == "fired"
    )


def test_the_registry_has_the_five_rules_and_they_are_in_the_catalog():
    assert sorted(NETWORK_RULE_CHECKS) == ["NL-1", "NL-2", "NL-4", "NL-5", "NL-6"]
    assert all(rule_id in RULES_BY_ID for rule_id in NETWORK_RULE_CHECKS)


def copy(other_claim_number, score=0.99):
    return {
        "document_id": "C-0000-fnol",
        "page_number": 1,
        "other_claim_id": f"C-{6000 + other_claim_number}",
        "other_document_id": f"C-{6000 + other_claim_number}-fnol",
        "other_page_number": 2,
        "score": score,
    }


def test_nl_4_fires_when_a_copy_was_found():
    result = check_nl_4(
        {"has_story_text": True, "copied_story": [copy(1), copy(2), copy(1)]}
    )
    assert result["status"] == "fired"
    assert result["proof"]["other_claims"] == ["C-6001", "C-6002"]  # sorted, no repeat
    assert (
        result["proof"]["copied_chunks"][0]
        == "C-0000-fnol page 1 ~ C-6001-fnol page 2 (0.990)"
    )


def test_nl_4_does_not_fire_without_a_copy():
    assert (
        check_nl_4({"has_story_text": True, "copied_story": []})["status"]
        == "not_fired"
    )


def test_nl_4_is_not_evaluated_without_story_text():
    assert (
        check_nl_4({"has_story_text": False, "copied_story": []})["status"]
        == "not_evaluated"
    )


def test_nl_4_cuts_the_proof_at_the_maximum():
    result = check_nl_4(
        {"has_story_text": True, "copied_story": [copy(number) for number in range(15)]}
    )
    assert len(result["proof"]["copied_chunks"]) == 10


# --- Same answers as the old system, on real claims ---
