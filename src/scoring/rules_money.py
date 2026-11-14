"""The yes/no checks of the rules about money: BF-1, BF-2, BF-3 and BF-4.

BF means "billing and expense": do the reserve and the payments look normal?
The reserve is the amount the insurer sets aside for the claim. It is updated over time.
Same idea as the other rule files: facts in, a rule result out, no database, no LLM.
Thresholds (50%, 1.5 times, 3 payments in 14 days) are in config.py.
"""

from src import config
from src.scoring.rule_results import fired_or_not, not_evaluated


def check_bf_1(facts):
    """Fast reserve rise: the reserve grows by more than 50% within 30 days."""
    events = facts["reserve_events"]
    if not events:
        return not_evaluated("no reserve history")
    # Compare every pair (earlier, later). The events are sorted by date, so "later" is really later.
    for first_index, first in enumerate(events):
        for later in events[first_index + 1 :]:
            days_between = (later["event_date"] - first["event_date"]).days
            grew_a_lot = later["reserve_total"] > first["reserve_total"] * (
                1 + config.RESERVE_RISE_SHARE
            )
            if days_between <= config.RESERVE_RISE_DAYS and grew_a_lot:
                return fired_or_not(
                    True,
                    {
                        "from_event": f"{first['event_id']} {first['event_date']} {first['reserve_total']:.2f}",
                        "to_event": f"{later['event_id']} {later['event_date']} {later['reserve_total']:.2f}",
                    },
                )
    return fired_or_not(False, {"reserve_events": len(events)})


def check_bf_2(facts):
    """Payments far above the reserve: the total paid is at least 1.5 times the latest reserve."""
    if not facts["reserve_events"]:
        return not_evaluated("no reserve history")
    latest_reserve_event = facts["reserve_events"][-1]
    total_paid = 0.0
    for payment in facts["payments"]:
        total_paid += payment["amount"]
    total_paid = round(total_paid, 2)
    return fired_or_not(
        total_paid
        >= config.PAID_TO_RESERVE_RATIO * latest_reserve_event["reserve_total"],
        {
            "total_paid": total_paid,
            "latest_reserve": latest_reserve_event["reserve_total"],
            "latest_reserve_event": latest_reserve_event["event_id"],
        },
    )


def check_bf_3(facts):
    """Many payments close together: 3 or more payments within 14 days."""
    payments = facts["payments"]
    group_size = config.PAYMENT_CLUSTER_COUNT
    # Payments are sorted by date. If any 3 in a row are close, the group is close.
    for start in range(len(payments) - group_size + 1):
        group = payments[start : start + group_size]
        days_between = (group[-1]["payment_date"] - group[0]["payment_date"]).days
        if days_between <= config.PAYMENT_CLUSTER_DAYS:
            return fired_or_not(
                True,
                {
                    "payments": [
                        f"{payment['payment_id']} {payment['payment_date']}"
                        for payment in group
                    ]
                },
            )
    return fired_or_not(False, {"payments": len(payments)})


def check_bf_4(facts):
    """Repair cost far above the first estimate: repair payments are at least 1.5 times the estimate."""
    if facts["repair_estimate_amount"] is None:
        return not_evaluated("no repair estimate")
    repair_paid = 0.0
    for payment in facts["payments"]:
        if payment["payment_type"] == "repair":
            repair_paid += payment["amount"]
    repair_paid = round(repair_paid, 2)
    return fired_or_not(
        repair_paid >= config.REPAIR_GROWTH_RATIO * facts["repair_estimate_amount"],
        {
            "repair_paid": repair_paid,
            "repair_estimate_amount": facts["repair_estimate_amount"],
        },
    )


MONEY_RULE_CHECKS = {
    "BF-1": check_bf_1,
    "BF-2": check_bf_2,
    "BF-3": check_bf_3,
    "BF-4": check_bf_4,
}


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    import datetime

    start = datetime.date(2025, 3, 1)

    def day(number):
        return start + datetime.timedelta(days=number)

    sample_facts = {
        "repair_estimate_amount": 2000.0,
        "reserve_events": [
            {"event_id": "R-1", "event_date": day(0), "reserve_total": 10000.0},
            {"event_id": "R-2", "event_date": day(20), "reserve_total": 16000.0},
        ],  # +60% in 20 days
        "payments": [
            {
                "payment_id": "P-1",
                "payment_date": day(1),
                "amount": 6000.0,
                "payment_type": "repair",
            },
            {
                "payment_id": "P-2",
                "payment_date": day(5),
                "amount": 6000.0,
                "payment_type": "medical",
            },
            {
                "payment_id": "P-3",
                "payment_date": day(9),
                "amount": 6000.0,
                "payment_type": "medical",
            },
        ],
    }
    for rule_id, check in MONEY_RULE_CHECKS.items():
        print(rule_id, check(sample_facts))
