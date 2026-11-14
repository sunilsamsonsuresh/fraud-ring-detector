"""The yes/no checks of the rules that compare dates: CT-1, CT-2, CT-3, CT-4 and CT-7.

CT means "coverage trigger": did the loss happen at a suspicious time for the policy?
Same idea as rules_tables.py: facts in, a rule result out, no database, no LLM.
Thresholds (30 days) are in config.py.
"""

from src import config
from src.scoring.rule_results import fired_or_not, not_evaluated


def check_ct_1(facts):
    """Loss soon after policy start: under 30 days after the customer joined."""
    policy = facts["policy"]
    if policy is None or policy["customer_since"] is None:
        return not_evaluated("no customer_since date")
    days = (facts["loss_date"] - policy["customer_since"]).days
    return fired_or_not(
        days < config.NEW_CUSTOMER_DAYS,
        {
            "customer_since": policy["customer_since"],
            "loss_date": facts["loss_date"],
            "days": days,
        },
    )


def check_ct_2(facts):
    """Loss soon after a coverage increase: 0 to 30 days after it."""
    policy = facts["policy"]
    if policy is None:
        return not_evaluated("no policy")
    increase_date = policy["last_coverage_increase_date"]
    if increase_date is None:
        # The table says "no coverage increase". That is a known answer, so the rule is checked and quiet.
        return fired_or_not(False, {"last_coverage_increase_date": None})
    days = (facts["loss_date"] - increase_date).days
    # A loss BEFORE the increase (negative days) is not suspicious, so the range starts at 0.
    return fired_or_not(
        0 <= days <= config.COVERAGE_INCREASE_DAYS,
        {
            "last_coverage_increase_date": increase_date,
            "loss_date": facts["loss_date"],
            "days": days,
        },
    )


def check_ct_3(facts):
    """Loss outside the policy dates: before it started, after it ended, or inside a lapse."""
    policy = facts["policy"]
    if (
        policy is None
        or policy["effective_date"] is None
        or policy["expiration_date"] is None
    ):
        return not_evaluated("no policy dates")
    loss_date = facts["loss_date"]
    outside_term = (
        loss_date < policy["effective_date"] or loss_date > policy["expiration_date"]
    )
    # A lapse is a gap in the cover. It has a start and an end, or neither.
    in_lapse = (
        policy["lapse_start"] is not None
        and policy["lapse_start"] <= loss_date <= policy["lapse_end"]
    )
    return fired_or_not(
        outside_term or in_lapse,
        {
            "loss_date": loss_date,
            "effective_date": policy["effective_date"],
            "expiration_date": policy["expiration_date"],
            "lapse_start": policy["lapse_start"],
            "lapse_end": policy["lapse_end"],
        },
    )


def check_ct_4(facts):
    """Late reporting: reported more than 30 days after the loss."""
    if facts["reported_date"] is None:
        return not_evaluated("no reported date")
    days = (facts["reported_date"] - facts["loss_date"]).days
    return fired_or_not(
        days > config.LATE_REPORT_DAYS,
        {
            "loss_date": facts["loss_date"],
            "reported_date": facts["reported_date"],
            "days": days,
        },
    )


def check_ct_7(facts):
    """Suit filed near the deadline: filed 0 to 30 days before the limitation deadline."""
    usable_lawsuits = []
    for lawsuit in facts["lawsuits"]:
        if (
            lawsuit["filed_date"] is not None
            and lawsuit["limitation_deadline"] is not None
        ):
            usable_lawsuits.append(lawsuit)
    if not usable_lawsuits:
        return not_evaluated("no lawsuit with a filed date and a deadline")
    for lawsuit in usable_lawsuits:
        days = (lawsuit["limitation_deadline"] - lawsuit["filed_date"]).days
        if 0 <= days <= config.SUIT_NEAR_DEADLINE_DAYS:
            return fired_or_not(
                True,
                {
                    "lawsuit_id": lawsuit["lawsuit_id"],
                    "filed_date": lawsuit["filed_date"],
                    "limitation_deadline": lawsuit["limitation_deadline"],
                    "days": days,
                },
            )
    first = usable_lawsuits[0]
    return fired_or_not(
        False,
        {
            "lawsuit_id": first["lawsuit_id"],
            "filed_date": first["filed_date"],
            "limitation_deadline": first["limitation_deadline"],
        },
    )


DATE_RULE_CHECKS = {
    "CT-1": check_ct_1,
    "CT-2": check_ct_2,
    "CT-3": check_ct_3,
    "CT-4": check_ct_4,
    "CT-7": check_ct_7,
}


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    import datetime

    loss = datetime.date(2025, 3, 1)
    sample_facts = {
        "loss_date": loss,
        "reported_date": loss + datetime.timedelta(days=45),  # CT-4 fires (45 > 30)
        "policy": {
            "effective_date": datetime.date(2025, 1, 1),
            "expiration_date": datetime.date(2025, 12, 31),
            "customer_since": loss
            - datetime.timedelta(days=10),  # CT-1 fires (10 < 30)
            "last_coverage_increase_date": loss
            - datetime.timedelta(days=5),  # CT-2 fires
            "lapse_start": None,
            "lapse_end": None,
        },  # CT-3 does not fire
        "lawsuits": [],  # CT-7 not evaluated
    }
    for rule_id, check in DATE_RULE_CHECKS.items():
        print(rule_id, check(sample_facts))
