"""Tests of src/scoring/rules_tables.py (new system).

Most tests use made-up facts, so they need no Neo4j. Some tests use real claims (Neo4j must be running).
"""

import datetime

from src import config
from src.scoring.rules_catalog import RULES_BY_ID
from src.scoring.rules_tables import (
    TABLE_RULE_CHECKS,
    check_bi_5,
    check_bi_6,
    check_nl_3,
)

LOSS = datetime.date(2024, 12, 15)


def day(days_after_loss):
    return LOSS + datetime.timedelta(days=days_after_loss)


def facts_with(**changes):
    facts = {
        "claim_id": "C-0000",
        "loss_date": LOSS,
        "attorney_retained_date": day(1),
        "visit_dates": [day(8)],
        "direct_links": [],
        "reported_date": day(2),
        "policy": None,
        "lawsuits": [],
    }
    facts.update(changes)
    return facts


def links(count, kind="clinic_and_attorney"):
    return [
        {
            "linked_claim_id": f"C-{2000 + number}",
            "kind": kind,
            "shared_value": "Clinic A + Attorney B",
        }
        for number in range(count)
    ]


def status(result):
    return result["status"]


# --- BI-5: attorney before first treatment ---


def test_bi_5_fires_when_the_attorney_comes_before_the_first_visit():
    result = check_bi_5(
        facts_with(attorney_retained_date=day(1), visit_dates=[day(8), day(9)])
    )
    assert status(result) == "fired"
    assert result["proof"] == {
        "attorney_retained_date": day(1),
        "first_visit_date": day(8),
    }


def test_bi_5_does_not_fire_on_the_same_day_or_later():
    assert (
        status(
            check_bi_5(facts_with(attorney_retained_date=day(8), visit_dates=[day(8)]))
        )
        == "not_fired"
    )
    assert (
        status(
            check_bi_5(facts_with(attorney_retained_date=day(9), visit_dates=[day(8)]))
        )
        == "not_fired"
    )


def test_bi_5_is_not_evaluated_without_an_attorney_or_without_visits():
    assert (
        status(check_bi_5(facts_with(attorney_retained_date=None))) == "not_evaluated"
    )
    assert status(check_bi_5(facts_with(visit_dates=[]))) == "not_evaluated"


# --- BI-6: heavy early treatment ---


def test_bi_6_needs_more_than_12_visits():
    assert status(check_bi_6(facts_with(visit_dates=[day(1)] * 12))) == "not_fired"
    result = check_bi_6(facts_with(visit_dates=[day(1)] * 13))
    assert status(result) == "fired"
    assert result["proof"]["visits_in_first_30_days"] == 13


def test_bi_6_counts_day_30_but_not_day_31_and_not_a_visit_before_the_loss():
    assert (
        check_bi_6(facts_with(visit_dates=[day(30)] * 13))["proof"][
            "visits_in_first_30_days"
        ]
        == 13
    )
    assert (
        check_bi_6(facts_with(visit_dates=[day(31)] * 13))["proof"][
            "visits_in_first_30_days"
        ]
        == 0
    )
    assert (
        check_bi_6(facts_with(visit_dates=[day(-1)] * 13))["proof"][
            "visits_in_first_30_days"
        ]
        == 0
    )


def test_bi_6_with_no_visits_does_not_fire():
    assert status(check_bi_6(facts_with(visit_dates=[]))) == "not_fired"


def test_bi_6_uses_the_numbers_in_config(monkeypatch):
    monkeypatch.setattr(config, "HEAVY_EARLY_TREATMENT_VISITS", 2)
    assert status(check_bi_6(facts_with(visit_dates=[day(1)] * 3))) == "fired"


# --- NL-3: same clinic and same attorney ---


def test_nl_3_needs_5_linked_claims():
    assert status(check_nl_3(facts_with(direct_links=links(4)))) == "not_fired"
    result = check_nl_3(facts_with(direct_links=links(5)))
    assert status(result) == "fired"
    assert result["proof"]["linked_claim_count"] == 5


def test_nl_3_counts_a_linked_claim_once_and_ignores_other_kinds():
    twice = links(4) + links(1)[:1] + links(4)[:1]  # 4 different claims, one repeated
    assert (
        check_nl_3(facts_with(direct_links=twice))["proof"]["linked_claim_count"] == 4
    )
    other_kinds = links(10, kind="phone") + links(10, kind="address")
    assert (
        check_nl_3(facts_with(direct_links=other_kinds))["proof"]["linked_claim_count"]
        == 0
    )


def test_nl_3_is_not_evaluated_without_an_attorney():
    assert (
        status(
            check_nl_3(facts_with(attorney_retained_date=None, direct_links=links(9)))
        )
        == "not_evaluated"
    )


def test_nl_3_proof_is_cut_at_10_links():
    result = check_nl_3(facts_with(direct_links=links(15)))
    assert result["proof"]["linked_claim_count"] == 15
    assert len(result["proof"]["links"]) == 10


# --- The registry ---


def test_the_registry_has_the_three_rules_and_they_are_in_the_catalog():
    assert sorted(TABLE_RULE_CHECKS) == ["BI-5", "BI-6", "NL-3"]
    assert all(rule_id in RULES_BY_ID for rule_id in TABLE_RULE_CHECKS)


# --- Same answers as the old system, on real claims ---
