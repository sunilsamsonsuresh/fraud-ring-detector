"""Plans for the lookalikes, the ordinary claims, and the network noise among the
ordinary claims.

Lookalikes are honest claims that look like fraud on purpose. Ordinary claims are honest
claims in no group. A few ordinary claims get network structure, so that the network rules
fire on honest claims at their base rate (config.HONEST_RULE_RATES):
  AS-6  2 claimants in one car, the police listed 1 occupant
  NL-2  one person with 3 claims (this also shares a phone, so it also counts for NL-1)
  NL-1  two different people with the same phone number
  NL-3  one honest "referral" attorney who sends every client to one clinic (also NL-6)
  NL-4  two claims with the same story text
  NL-5  one law firm and one expert in 4 suits within a few months
"""

import datetime

from src import config
from src.data_generation.claim_plan_blocks import (
    GENERAL_LOSS_DATES,
    LAWSUIT_LOSS_DATES,
    new_incident,
    new_person,
    new_plan,
    new_record,
    random_date,
)

FAMILY_FIRST_LOSS_DATES = (datetime.date(2023, 1, 1), datetime.date(2024, 12, 31))
# lookalike group -> the rule it fires on purpose
DESIGNED_TRIGGERS = {
    "late_reporter": "CT-4",
    "new_customer": "CT-1",
    "serious_injury": "BI-6",
    "pre_existing": "BI-4",
}


def plan_families(fake, world):
    """Two family members: same address, phone and last name, different birth dates, one household
    policy, two separate accidents."""
    plans = []
    for _ in range(config.FAMILY_PAIRS):
        first_loss = random_date(fake, FAMILY_FIRST_LOSS_DATES)
        second_loss = first_loss + datetime.timedelta(days=fake.random.randint(20, 200))
        first_person = new_person(
            fake, world, fake.random.choice(["Houston", "Katy", "Pearland", "Baytown"])
        )
        second_person = new_person(
            fake,
            world,
            first_person["address"]["city"],
            phone_number=first_person["phone_number"],
            address=first_person["address"],
            last_name=first_person["last_name"],
        )
        if second_person["date_of_birth"] == first_person["date_of_birth"]:
            second_person["date_of_birth"] -= datetime.timedelta(days=400)
        policy = new_record(world, "policies")
        for person, loss_date in [
            (first_person, first_loss),
            (second_person, second_loss),
        ]:
            incident = new_incident(fake, world, loss_date, person["address"]["city"])
            plans.append(
                new_plan(fake, world, "family", incident, "driver", person, policy)
            )
    return plans


def plan_multi_claimant_incidents(fake, world):
    """One real accident, 2 to 4 honest claimants: same story, clinic and attorney. The police
    list at least as many occupants as there are claimants."""
    plans = []
    for number, size in enumerate(config.MULTI_CLAIMANT_INCIDENT_SIZES, start=1):
        incident = new_incident(
            fake, world, random_date(fake, GENERAL_LOSS_DATES), has_police_report=True
        )
        incident["occupants_listed"] = size + fake.random.randint(0, 1)
        clinic_id = fake.random.choice(world["normal_clinic_ids"])
        attorney_id = fake.random.choice(world["normal_attorney_ids"])
        driver = None
        for seat in range(size):
            if seat == 0:
                plan = new_plan(
                    fake, world, "multi_claimant_incident", incident, "driver"
                )
                driver = plan
            else:
                plan = new_plan(
                    fake,
                    world,
                    "multi_claimant_incident",
                    incident,
                    "passenger",
                    None,
                    driver["policy"],
                    driver["vehicle"],
                )
            plan["clinic_id"] = clinic_id
            plan["attorney_id"] = attorney_id
            plan["story_group"] = f"incident_{number}"
            plans.append(plan)
    return plans


def plan_simple_lookalikes(fake, world):
    plans = []
    sizes = config.LOOKALIKE_GROUP_SIZES
    for number in range(sizes["busy_law_firm"]):
        has_lawsuit = number < config.BUSY_LAW_FIRM_LAWSUITS
        loss_dates = LAWSUIT_LOSS_DATES if has_lawsuit else GENERAL_LOSS_DATES
        plan = new_plan(
            fake,
            world,
            "busy_law_firm",
            new_incident(fake, world, random_date(fake, loss_dates)),
            "driver",
        )
        plan["attorney_candidates"] = world["busy_attorney_ids"]
        plan["wants_attorney"] = True
        plan["has_lawsuit"] = has_lawsuit
        plans.append(plan)
    for _ in range(sizes["busy_repair_shop"]):
        plan = new_plan(
            fake,
            world,
            "busy_repair_shop",
            new_incident(fake, world, random_date(fake, GENERAL_LOSS_DATES)),
            "driver",
        )
        plan["repair_shop_id"] = world["busy_repair_shop_id"]
        plans.append(plan)
    for _ in range(sizes["large_clinic"]):
        plan = new_plan(
            fake,
            world,
            "large_clinic",
            new_incident(fake, world, random_date(fake, GENERAL_LOSS_DATES)),
            "driver",
        )
        plan["clinic_id"] = world["large_clinic_id"]
        plans.append(plan)
    for group, rule_id in DESIGNED_TRIGGERS.items():
        for _ in range(sizes[group]):
            plan = new_plan(
                fake,
                world,
                group,
                new_incident(fake, world, random_date(fake, GENERAL_LOSS_DATES)),
                "driver",
            )
            plan["signals"].add(rule_id)
            plans.append(plan)
    return plans


def plan_ordinary(fake, world, claim_count, lawsuit_count):
    plans = []
    for number in range(claim_count):
        has_lawsuit = number < lawsuit_count
        loss_dates = LAWSUIT_LOSS_DATES if has_lawsuit else GENERAL_LOSS_DATES
        plan = new_plan(
            fake,
            world,
            "ordinary",
            new_incident(fake, world, random_date(fake, loss_dates)),
            "driver",
        )
        plan["has_lawsuit"] = has_lawsuit
        plans.append(plan)
    return plans


def take(fake, free_plans, count, condition=None):
    """Remove `count` random plans (that meet the condition) from free_plans and return them."""
    candidates = []
    for plan in free_plans:
        if condition is None or condition(plan):
            candidates.append(plan)
    chosen = fake.random.sample(candidates, count)
    for plan in chosen:
        free_plans.remove(plan)
    return chosen


def add_ordinary_network_noise(fake, world, ordinary):
    """Plant the base-rate network structure on a few ordinary claims. Each claim gets at most one."""
    rates = config.HONEST_RULE_RATES
    free = list(ordinary)
    with_police = [plan for plan in ordinary if plan["incident"]["has_police_report"]]
    # Groups come in pairs or triples: round to the NEAREST whole group, so the rate stays close.
    pair_count = round(rates["AS-6"] * len(with_police) / 2)
    chosen = take(
        fake,
        free,
        2 * pair_count,
        lambda plan: plan["incident"]["has_police_report"] and not plan["has_lawsuit"],
    )
    for driver, passenger in zip(chosen[0::2], chosen[1::2]):
        passenger.update(
            {
                "incident": driver["incident"],
                "role": "passenger",
                "policy": driver["policy"],
                "vehicle": driver["vehicle"],
                "repair_shop_id": None,
                "repair_estimate_amount": None,
            }
        )
        driver["incident"]["occupants_listed"] = 1
        driver["tags"].add("as6_pair")
        passenger["tags"].add("as6_pair")

    triple_count = round(rates["NL-2"] * len(ordinary) / 3)
    chosen = take(fake, free, 3 * triple_count)
    for first, second, third in zip(chosen[0::3], chosen[1::3], chosen[2::3]):
        for plan in [first, second, third]:
            plan["person"] = first["person"]
            plan["tags"].add("repeat_claimant")

    nl1_pair_count = max(
        0, round((rates["NL-1"] * len(ordinary) - 3 * triple_count) / 2)
    )
    chosen = take(fake, free, 2 * nl1_pair_count)
    for first, second in zip(chosen[0::2], chosen[1::2]):
        second["person"]["phone_number"] = first["person"]["phone_number"]
        first["tags"].add("shared_phone_pair")
        second["tags"].add("shared_phone_pair")

    referral_clinic_id = fake.random.choice(world["normal_clinic_ids"])
    for plan in take(fake, free, round(rates["NL-3"] * len(ordinary))):
        plan["clinic_id"] = referral_clinic_id
        plan["attorney_id"] = world["referral_attorney_ids"][0]
        plan["tags"].add("referral_group")

    chosen = take(fake, free, 2 * round(rates["NL-4"] * len(ordinary) / 2))
    for number, (first, second) in enumerate(zip(chosen[0::2], chosen[1::2]), start=1):
        first["story_group"] = second["story_group"] = f"copy_pair_{number}"

    with_lawsuit = [plan for plan in ordinary if plan["has_lawsuit"]]
    _law_firm_id, attorney_ids = fake.random.choice(world["normal_law_firms"])
    first_loss = random_date(
        fake, (datetime.date(2023, 1, 1), datetime.date(2024, 2, 28))
    )
    for plan in take(
        fake,
        free,
        round(rates["NL-5"] * len(with_lawsuit)),
        lambda plan: plan["has_lawsuit"],
    ):
        plan["incident"]["loss_date"] = first_loss + datetime.timedelta(
            days=fake.random.randint(0, 120)
        )
        plan["clinic_id"] = fake.random.choice(world["normal_clinic_ids"])
        plan["attorney_id"] = fake.random.choice(attorney_ids)
        plan["expert_id"] = world["nl5_noise_expert_id"]
        plan["lawsuit_kind"] = "suit_group"
        plan["tags"].add("firm_expert_group")


def plan_honest_claims(fake, world, fraud_and_co_claimant_count):
    plans = plan_families(fake, world) + plan_multi_claimant_incidents(fake, world)
    plans.extend(plan_simple_lookalikes(fake, world))
    ordinary_count = config.TOTAL_CLAIMS - fraud_and_co_claimant_count - len(plans)
    ordinary_lawsuits = (
        config.TOTAL_LAWSUITS
        - config.FRAUD_TYPE_SIZES["ring_c"]
        - config.BUSY_LAW_FIRM_LAWSUITS
    )
    ordinary = plan_ordinary(fake, world, ordinary_count, ordinary_lawsuits)
    add_ordinary_network_noise(fake, world, ordinary)
    return plans + ordinary


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.plan_honest_claims      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    from faker import Faker

    from src.data_generation.claim_plan_blocks import make_world
    from src.data_generation.generate_tables import TABLE_NAMES

    fake = Faker("en_US")
    fake.seed_instance(42)
    world = make_world(fake, {table_name: [] for table_name in TABLE_NAMES})

    families = plan_families(fake, world)
    print(
        "1. plan_families:",
        len(families),
        "plans | same phone in a pair:",
        families[0]["person"]["phone_number"] == families[1]["person"]["phone_number"],
    )
    plans = plan_honest_claims(
        fake, world, 66
    )  # 66 = the fraud claims and the jump-in co-claimants
    groups = {}
    for plan in plans:
        groups[plan["group"]] = groups.get(plan["group"], 0) + 1
    print("2. plan_honest_claims:", len(plans), "plans", groups)
