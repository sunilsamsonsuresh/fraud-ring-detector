"""Tests of src/scoring/rules_dates.py (new system).

Most tests use made-up facts, so they need no Neo4j. Some tests use real claims (Neo4j must be running).
"""

import datetime

from src import config
from src.scoring.rules_catalog import RULES_BY_ID
from src.scoring.rules_dates import (
    DATE_RULE_CHECKS,
    check_ct_1,
    check_ct_2,
    check_ct_3,
    check_ct_4,
    check_ct_7,
)

LOSS = datetime.date(2025, 3, 1)


def day(days_after_loss):
    return LOSS + datetime.timedelta(days=days_after_loss)


def policy_with(**changes):
    policy = {
        "effective_date": day(-200),
        "expiration_date": day(160),
        "customer_since": day(-900),
        "last_coverage_increase_date": None,
        "lapse_start": None,
        "lapse_end": None,
    }
    policy.update(changes)
    return policy


def facts_with(**changes):
    facts = {
        "loss_date": LOSS,
        "reported_date": day(2),
        "policy": policy_with(),
        "lawsuits": [],
    }
    facts.update(changes)
    return facts


def lawsuit(filed_after_loss, deadline_after_loss):
    return {
        "lawsuit_id": "L-1",
        "filed_date": day(filed_after_loss),
        "limitation_deadline": day(deadline_after_loss),
    }


def status(result):
    return result["status"]


# --- CT-1: loss soon after policy start (under 30 days) ---


def test_ct_1_fires_under_30_days_and_not_at_30():
    assert (
        status(check_ct_1(facts_with(policy=policy_with(customer_since=day(-29)))))
        == "fired"
    )
    assert (
        status(check_ct_1(facts_with(policy=policy_with(customer_since=day(-30)))))
        == "not_fired"
    )


def test_ct_1_is_not_evaluated_without_a_policy_or_a_date():
    assert status(check_ct_1(facts_with(policy=None))) == "not_evaluated"
    assert (
        status(check_ct_1(facts_with(policy=policy_with(customer_since=None))))
        == "not_evaluated"
    )


# --- CT-2: loss soon after a coverage increase (0 to 30 days) ---


def test_ct_2_counts_day_0_and_day_30_but_not_day_31_and_not_a_later_increase():
    for days_before, expected in [
        (0, "fired"),
        (30, "fired"),
        (31, "not_fired"),
        (-1, "not_fired"),
    ]:
        facts = facts_with(
            policy=policy_with(last_coverage_increase_date=day(-days_before))
        )
        assert status(check_ct_2(facts)) == expected, days_before


def test_ct_2_no_increase_is_checked_and_quiet_and_no_policy_is_not_evaluated():
    assert status(check_ct_2(facts_with())) == "not_fired"
    assert status(check_ct_2(facts_with(policy=None))) == "not_evaluated"


# --- CT-3: loss outside the policy dates ---


def test_ct_3_fires_before_the_start_after_the_end_and_inside_a_lapse():
    assert (
        status(check_ct_3(facts_with(policy=policy_with(effective_date=day(1)))))
        == "fired"
    )
    assert (
        status(check_ct_3(facts_with(policy=policy_with(expiration_date=day(-1)))))
        == "fired"
    )
    assert (
        status(
            check_ct_3(
                facts_with(policy=policy_with(lapse_start=day(-3), lapse_end=day(3)))
            )
        )
        == "fired"
    )


def test_ct_3_does_not_fire_on_the_first_or_last_day_of_the_policy_or_the_lapse_edges_outside():
    assert (
        status(check_ct_3(facts_with(policy=policy_with(effective_date=day(0)))))
        == "not_fired"
    )
    assert (
        status(check_ct_3(facts_with(policy=policy_with(expiration_date=day(0)))))
        == "not_fired"
    )
    assert (
        status(
            check_ct_3(
                facts_with(policy=policy_with(lapse_start=day(1), lapse_end=day(9)))
            )
        )
        == "not_fired"
    )
    assert status(check_ct_3(facts_with())) == "not_fired"


def test_ct_3_is_not_evaluated_without_policy_dates():
    assert status(check_ct_3(facts_with(policy=None))) == "not_evaluated"
    assert (
        status(check_ct_3(facts_with(policy=policy_with(expiration_date=None))))
        == "not_evaluated"
    )


# --- CT-4: late reporting (over 30 days) ---


def test_ct_4_fires_over_30_days_and_not_at_30():
    assert status(check_ct_4(facts_with(reported_date=day(31)))) == "fired"
    assert status(check_ct_4(facts_with(reported_date=day(30)))) == "not_fired"


def test_ct_4_is_not_evaluated_without_a_reported_date():
    assert status(check_ct_4(facts_with(reported_date=None))) == "not_evaluated"


# --- CT-7: suit filed near the deadline (0 to 30 days before it) ---


def test_ct_7_fires_when_filed_0_to_30_days_before_the_deadline():
    for days_before_deadline, expected in [
        (0, "fired"),
        (30, "fired"),
        (31, "not_fired"),
        (-1, "not_fired"),
    ]:
        facts = facts_with(lawsuits=[lawsuit(100, 100 + days_before_deadline)])
        assert status(check_ct_7(facts)) == expected, days_before_deadline


def test_ct_7_looks_at_every_lawsuit():
    facts = facts_with(lawsuits=[lawsuit(100, 300), lawsuit(200, 210)])
    result = check_ct_7(facts)
    assert status(result) == "fired"
    assert result["proof"]["days"] == 10


def test_ct_7_is_not_evaluated_without_a_usable_lawsuit():
    assert status(check_ct_7(facts_with(lawsuits=[]))) == "not_evaluated"
    assert (
        status(
            check_ct_7(
                facts_with(
                    lawsuits=[
                        {
                            "lawsuit_id": "L-1",
                            "filed_date": day(5),
                            "limitation_deadline": None,
                        }
                    ]
                )
            )
        )
        == "not_evaluated"
    )


def test_the_thresholds_are_in_config(monkeypatch):
    monkeypatch.setattr(config, "LATE_REPORT_DAYS", 5)
    assert status(check_ct_4(facts_with(reported_date=day(6)))) == "fired"


def test_the_registry_has_the_five_rules_and_they_are_in_the_catalog():
    assert sorted(DATE_RULE_CHECKS) == ["CT-1", "CT-2", "CT-3", "CT-4", "CT-7"]
    assert all(rule_id in RULES_BY_ID for rule_id in DATE_RULE_CHECKS)


# --- Same answers as the old system, on real claims ---
