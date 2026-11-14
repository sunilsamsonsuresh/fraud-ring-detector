"""Tests of src/scoring/rules_money.py (new system).

Most tests use made-up facts, so they need no Neo4j. Some tests use real claims (Neo4j must be running).
"""

import datetime

from src import config
from src.scoring.rules_catalog import RULES_BY_ID
from src.scoring.rules_money import (
    MONEY_RULE_CHECKS,
    check_bf_1,
    check_bf_2,
    check_bf_3,
    check_bf_4,
)

START = datetime.date(2025, 3, 1)


def day(number):
    return START + datetime.timedelta(days=number)


def reserve(event_number, days, total):
    return {
        "event_id": f"R-{event_number}",
        "event_date": day(days),
        "reserve_total": total,
    }


def payment(payment_number, days, amount, payment_type="medical"):
    return {
        "payment_id": f"P-{payment_number}",
        "payment_date": day(days),
        "amount": amount,
        "payment_type": payment_type,
    }


def facts_with(**changes):
    facts = {"repair_estimate_amount": 2000.0, "reserve_events": [], "payments": []}
    facts.update(changes)
    return facts


def status(result):
    return result["status"]


# --- BF-1: fast reserve rise (more than 50% within 30 days) ---


def test_bf_1_needs_more_than_50_percent():
    assert (
        status(
            check_bf_1(
                facts_with(
                    reserve_events=[reserve(1, 0, 10000.0), reserve(2, 10, 15000.0)]
                )
            )
        )
        == "not_fired"
    )
    assert (
        status(
            check_bf_1(
                facts_with(
                    reserve_events=[reserve(1, 0, 10000.0), reserve(2, 10, 15001.0)]
                )
            )
        )
        == "fired"
    )


def test_bf_1_counts_day_30_but_not_day_31():
    assert (
        status(
            check_bf_1(
                facts_with(
                    reserve_events=[reserve(1, 0, 10000.0), reserve(2, 30, 20000.0)]
                )
            )
        )
        == "fired"
    )
    assert (
        status(
            check_bf_1(
                facts_with(
                    reserve_events=[reserve(1, 0, 10000.0), reserve(2, 31, 20000.0)]
                )
            )
        )
        == "not_fired"
    )


def test_bf_1_compares_every_pair_not_only_neighbours():
    # 10000 -> 12000 -> 16000: each step is under 50%, but the first and the last are +60% within 30 days.
    events = [reserve(1, 0, 10000.0), reserve(2, 10, 12000.0), reserve(3, 20, 16000.0)]
    result = check_bf_1(facts_with(reserve_events=events))
    assert status(result) == "fired"
    assert result["proof"]["from_event"].startswith("R-1") and result["proof"][
        "to_event"
    ].startswith("R-3")


def test_bf_1_a_falling_reserve_does_not_fire_and_no_history_is_not_evaluated():
    assert (
        status(
            check_bf_1(
                facts_with(
                    reserve_events=[reserve(1, 0, 10000.0), reserve(2, 5, 1000.0)]
                )
            )
        )
        == "not_fired"
    )
    assert status(check_bf_1(facts_with(reserve_events=[]))) == "not_evaluated"


# --- BF-2: payments far above the reserve (at least 1.5 times the latest reserve) ---


def test_bf_2_fires_at_exactly_1_5_times_the_latest_reserve():
    events = [
        reserve(1, 0, 99999.0),
        reserve(2, 5, 10000.0),
    ]  # only the LATEST reserve counts
    assert (
        status(
            check_bf_2(
                facts_with(reserve_events=events, payments=[payment(1, 1, 14999.99)])
            )
        )
        == "not_fired"
    )
    result = check_bf_2(
        facts_with(
            reserve_events=events,
            payments=[payment(1, 1, 9000.0), payment(2, 2, 6000.0)],
        )
    )
    assert status(result) == "fired"
    assert result["proof"] == {
        "total_paid": 15000.0,
        "latest_reserve": 10000.0,
        "latest_reserve_event": "R-2",
    }


def test_bf_2_is_not_evaluated_without_a_reserve():
    assert (
        status(check_bf_2(facts_with(reserve_events=[], payments=[payment(1, 1, 5.0)])))
        == "not_evaluated"
    )


# --- BF-3: many payments close together (3 or more within 14 days) ---


def test_bf_3_counts_14_days_but_not_15():
    assert (
        status(
            check_bf_3(
                facts_with(
                    payments=[
                        payment(1, 0, 1.0),
                        payment(2, 7, 1.0),
                        payment(3, 14, 1.0),
                    ]
                )
            )
        )
        == "fired"
    )
    assert (
        status(
            check_bf_3(
                facts_with(
                    payments=[
                        payment(1, 0, 1.0),
                        payment(2, 7, 1.0),
                        payment(3, 15, 1.0),
                    ]
                )
            )
        )
        == "not_fired"
    )


def test_bf_3_needs_three_payments_and_finds_a_group_later_in_the_list():
    assert (
        status(
            check_bf_3(facts_with(payments=[payment(1, 0, 1.0), payment(2, 1, 1.0)]))
        )
        == "not_fired"
    )
    assert status(check_bf_3(facts_with(payments=[]))) == "not_fired"
    spread_then_close = [
        payment(1, 0, 1.0),
        payment(2, 60, 1.0),
        payment(3, 100, 1.0),
        payment(4, 101, 1.0),
        payment(5, 102, 1.0),
    ]
    result = check_bf_3(facts_with(payments=spread_then_close))
    assert status(result) == "fired"
    assert [text.split()[0] for text in result["proof"]["payments"]] == [
        "P-3",
        "P-4",
        "P-5",
    ]


# --- BF-4: repair cost far above the first estimate (at least 1.5 times) ---


def test_bf_4_fires_at_exactly_1_5_times_and_counts_only_repair_payments():
    medical = payment(1, 1, 50000.0, "medical")
    assert (
        status(
            check_bf_4(facts_with(payments=[medical, payment(2, 2, 2999.99, "repair")]))
        )
        == "not_fired"
    )
    result = check_bf_4(
        facts_with(
            payments=[
                medical,
                payment(2, 2, 1000.0, "repair"),
                payment(3, 3, 2000.0, "repair"),
            ]
        )
    )
    assert status(result) == "fired"
    assert result["proof"] == {"repair_paid": 3000.0, "repair_estimate_amount": 2000.0}


def test_bf_4_is_not_evaluated_without_an_estimate_and_quiet_without_payments():
    assert (
        status(check_bf_4(facts_with(repair_estimate_amount=None))) == "not_evaluated"
    )
    assert status(check_bf_4(facts_with(payments=[]))) == "not_fired"


def test_the_thresholds_are_in_config(monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_CLUSTER_COUNT", 2)
    assert (
        status(
            check_bf_3(facts_with(payments=[payment(1, 0, 1.0), payment(2, 1, 1.0)]))
        )
        == "fired"
    )


def test_the_registry_has_the_four_rules_and_they_are_in_the_catalog():
    assert sorted(MONEY_RULE_CHECKS) == ["BF-1", "BF-2", "BF-3", "BF-4"]
    assert all(rule_id in RULES_BY_ID for rule_id in MONEY_RULE_CHECKS)


# --- Same answers as the old system, on real claims ---
