"""Policy dates and lawsuit rows from the planted signals.

Honest values keep a safe distance from every rule threshold, so a rule fires only where
it was planted. Examples: an honest customer joined at least 60 days before the loss
(CT-1 fires under 30); an honest suit is filed 120 to 540 days after the loss, so at
least 190 days before the 2-year deadline (CT-7 fires at 30 or less).
"""

from src import config
from src.data_generation.table_row_helpers import (
    DATA_AS_OF_DATE,
    add_days,
    add_years,
    make_id,
)

POLICY_LIMITS = [25000, 50000, 100000, 250000]
HONEST_COVERAGE_INCREASE_CHANCE = 0.25
HONEST_PAST_LAPSE_CHANCE = 0.05


def random_day_between(fake, first_date, last_date):
    if last_date <= first_date:
        return first_date
    return add_days(first_date, fake.random.randint(0, (last_date - first_date).days))


def add_policy_row(fake, tables, plans_on_policy):
    """One policy row for all the claims that use it. Return the policy ID.
    Only a policy with one plain claim can carry CT-1, CT-2 or CT-3 (plan_signals_and_features.py)."""
    loss_dates = sorted(plan["incident"]["loss_date"] for plan in plans_on_policy)
    first_loss, last_loss = loss_dates[0], loss_dates[-1]
    signals = set()
    for plan in plans_on_policy:
        signals.update(plan["signals"])

    lapse_start = lapse_end = coverage_increase = None
    if "CT-1" in signals:
        # A new customer. With CT-3 as well, the policy even starts AFTER the loss (backdating).
        customer_since = add_days(first_loss, -fake.random.randint(1, 25))
        if "CT-3" in signals:
            customer_since = add_days(first_loss, fake.random.randint(1, 20))
        effective_date = customer_since
    else:
        customer_since = add_days(first_loss, -fake.random.randint(60, 3000))
        lowest_start = max(customer_since, add_days(last_loss, -364))
        effective_date = random_day_between(
            fake, lowest_start, add_days(first_loss, -1)
        )
        if "CT-3" in signals:
            if (
                fake.random.random() < 0.5
            ):  # the policy had expired: the term ended 1 to 20 days before the loss
                effective_date = add_days(first_loss, -366 - fake.random.randint(1, 20))
                customer_since = min(customer_since, effective_date)
            else:  # the loss falls inside a lapse in coverage
                lapse_start = add_days(first_loss, -fake.random.randint(3, 20))
                lapse_end = add_days(first_loss, fake.random.randint(3, 30))
                effective_date = min(effective_date, lapse_start)
        elif fake.random.random() < HONEST_PAST_LAPSE_CHANCE:
            # An old lapse that ended long before this term, so it never covers the loss.
            gap_end = add_days(effective_date, -60)
            if (gap_end - customer_since).days > 60:
                lapse_start = random_day_between(
                    fake, customer_since, add_days(gap_end, -45)
                )
                lapse_end = add_days(lapse_start, fake.random.randint(10, 40))
    if "CT-2" in signals:
        coverage_increase = add_days(first_loss, -fake.random.randint(1, 25))
        customer_since = min(customer_since, coverage_increase)
    elif (
        fake.random.random() < HONEST_COVERAGE_INCREASE_CHANCE
        and (first_loss - customer_since).days > 150
    ):
        coverage_increase = random_day_between(
            fake, add_days(customer_since, 30), add_days(first_loss, -90)
        )

    per_person_limit = fake.random.choice(POLICY_LIMITS)
    policy_id = make_id(tables, "policies", "POL")
    tables["policies"].append(
        {
            "policy_id": policy_id,
            "effective_date": effective_date,
            "expiration_date": add_years(effective_date, 1),
            "bodily_injury_limit": per_person_limit,  # v1 column, kept: the same as per_person_limit
            "customer_since": customer_since,
            "last_coverage_increase_date": coverage_increase,
            "lapse_start": lapse_start,
            "lapse_end": lapse_end,
            "per_person_limit": per_person_limit,
            "per_accident_limit": 2 * per_person_limit,
        }
    )
    return policy_id


def add_lawsuit_rows(fake, tables, plan, claim_row, law_firm_id):
    loss_date = plan["incident"]["loss_date"]
    deadline = add_years(loss_date, config.FILING_DEADLINE_YEARS)
    if "CT-7" in plan["signals"]:
        filed_date = add_days(deadline, -fake.random.randint(1, 25))
    elif plan["lawsuit_kind"] == "suit_group":
        filed_date = add_days(loss_date, fake.random.randint(200, 260))
    else:
        filed_date = add_days(loss_date, fake.random.randint(120, 540))
    if plan.get("demand_kind") == "ring_c":
        demand_amount = int(round(fake.random.uniform(73500, 76500), -2))
    else:
        demand_amount = int(round(fake.random.uniform(25000, 250000), -3))

    lawsuit_id = make_id(tables, "lawsuits", "LS")
    settlement_date = add_days(filed_date, fake.random.randint(60, 300))
    is_settled = fake.random.random() < 0.6 and settlement_date <= DATA_AS_OF_DATE
    tables["lawsuits"].append(
        {
            "lawsuit_id": lawsuit_id,
            "claim_id": claim_row["claim_id"],
            "court_id": fake.random.choice(tables["courts"])["court_id"],
            "plaintiff_law_firm_id": law_firm_id,
            "expert_id": plan["expert_id"],
            "filed_date": filed_date,
            "limitation_deadline": deadline,
            "demand_amount": demand_amount,
            "status": "settled" if is_settled else "pending",
        }
    )
    if is_settled:
        tables["settlements"].append(
            {
                "settlement_id": make_id(tables, "settlements", "ST"),
                "lawsuit_id": lawsuit_id,
                "settlement_date": settlement_date,
                "settlement_amount": int(
                    round(demand_amount * fake.random.uniform(0.35, 0.75), -2)
                ),
            }
        )
    return filed_date, settlement_date if is_settled else None


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.write_policy_and_lawsuit_rows      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    import datetime

    from faker import Faker

    fake = Faker("en_US")
    fake.seed_instance(42)
    loss = datetime.date(2024, 6, 1)
    tables = {"policies": []}
    # A plan with the planted signal CT-1 (new customer): the customer joined less than 30 days before the loss.
    add_policy_row(
        fake, tables, [{"incident": {"loss_date": loss}, "signals": {"CT-1"}}]
    )
    policy = tables["policies"][0]
    print(
        "1. CT-1 policy: customer_since",
        policy["customer_since"],
        "| days before the loss:",
        (loss - policy["customer_since"]).days,
    )
    add_policy_row(fake, tables, [{"incident": {"loss_date": loss}, "signals": set()}])
    policy = tables["policies"][1]
    print(
        "2. honest policy: days before the loss:",
        (loss - policy["customer_since"]).days,
        "(always 60 or more)",
    )
