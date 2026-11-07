"""Decide who plays which role: the 3 fraud rings, the innocent overlaps
and the normal claims (PLAN.md, section A3).

Each claim starts as a "plan": a dict that says which phone, address,
repair shop, clinic, attorney, dates, amounts and lawsuit the claim uses.
claim_rows.py later turns each plan into table rows.
A plan value of None means "make a new, unshared one".
"""

import datetime

from src.datagen.table_rows import (
    CITIES, COUNTIES, add_address, add_court, add_expert, add_law_firm,
    add_policy, add_provider, add_vehicle, new_phone_number,
)

TOTAL_CLAIMS = 500
TOTAL_LAWSUITS = 50
RING_A_SIZE = 12
RING_B_SIZE = 15
RING_C_SIZE = 10
FAMILY_SIZES = [2, 2, 2, 3, 2, 3, 2]
BUSY_LAW_FIRM_CLAIMS = 40
BUSY_LAW_FIRM_LAWSUITS = 8
POPULAR_REPAIR_SHOP_CLAIMS = 45
LARGE_CLINIC_CLAIMS = 40

FIRST_LOSS_DATE = datetime.date(2023, 1, 1)
LAST_LOSS_DATE = datetime.date(2025, 6, 30)
# Lawsuit claims are older, so every lawsuit is filed before DATA_AS_OF_DATE.
LAST_LAWSUIT_LOSS_DATE = datetime.date(2024, 12, 31)

ACCIDENT_TYPES = ["rear-end collision", "side impact at intersection", "sideswipe while changing lanes",
                  "parking lot collision", "low-speed head-on collision", "hit while turning left"]
INJURY_TYPES = ["neck strain", "back strain", "neck and back strain", "shoulder injury",
                "knee injury", "concussion", "wrist fracture", "whiplash"]


def add_reference_entities(fake, tables, used_phone_numbers):
    """Add courts, experts, providers and law firms. Return the role of each.

    Roles are shuffled before the rows are made, so a special shop or firm
    does not get a give-away ID such as the first or the last one.
    """
    entities = {"normal_repair_shop_ids": [], "normal_clinic_ids": [],
                "normal_attorney_ids": [], "normal_expert_ids": []}

    for county in COUNTIES:
        add_court(tables, county)

    expert_roles = ["normal"] * 12 + ["ring_c"]
    fake.random.shuffle(expert_roles)
    for role in expert_roles:
        expert_id = add_expert(fake, tables)
        if role == "ring_c":
            entities["ring_c_expert_id"] = expert_id
        else:
            entities["normal_expert_ids"].append(expert_id)

    shop_roles = ["normal"] * 40 + ["ring_a", "popular"]
    fake.random.shuffle(shop_roles)
    for role in shop_roles:
        shop_id = add_provider(fake, tables, "repair_shop", used_phone_numbers)
        if role == "ring_a":
            entities["ring_a_repair_shop_id"] = shop_id
        elif role == "popular":
            entities["popular_repair_shop_id"] = shop_id
        else:
            entities["normal_repair_shop_ids"].append(shop_id)

    clinic_roles = ["normal"] * 30 + ["ring_b", "large"]
    fake.random.shuffle(clinic_roles)
    for role in clinic_roles:
        clinic_id = add_provider(fake, tables, "clinic", used_phone_numbers)
        if role == "ring_b":
            entities["ring_b_clinic_id"] = clinic_id
        elif role == "large":
            entities["large_clinic_id"] = clinic_id
        else:
            entities["normal_clinic_ids"].append(clinic_id)

    firm_roles = ["normal"] * 14 + ["busy", "ring_b", "ring_c"]
    fake.random.shuffle(firm_roles)
    for role in firm_roles:
        if role == "normal":
            law_firm_id, attorney_ids = add_law_firm(fake, tables, fake.random.randint(1, 3), used_phone_numbers)
            entities["normal_attorney_ids"].extend(attorney_ids)
        elif role == "busy":
            law_firm_id, attorney_ids = add_law_firm(fake, tables, 5, used_phone_numbers)
            entities["busy_law_firm_id"] = law_firm_id
            entities["busy_law_firm_attorney_ids"] = attorney_ids
        elif role == "ring_b":
            law_firm_id, attorney_ids = add_law_firm(fake, tables, 2, used_phone_numbers)
            entities["ring_b_law_firm_id"] = law_firm_id
            entities["ring_b_attorney_ids"] = attorney_ids
        else:
            law_firm_id, attorney_ids = add_law_firm(fake, tables, 2, used_phone_numbers)
            entities["ring_c_law_firm_id"] = law_firm_id
            entities["ring_c_attorney_ids"] = attorney_ids

    return entities


def random_medical_amounts(fake):
    """Return (treatment_visits, medical_bill_amount) for a normal claim."""
    treatment_visits = fake.random.randint(2, 30)
    medical_bill_amount = round(treatment_visits * fake.random.uniform(110, 320), 2)
    return treatment_visits, medical_bill_amount


def plan_ordinary_claim(fake, entities, group, has_lawsuit):
    """Plan a normal claim. The pattern functions below change a few values."""
    if has_lawsuit:
        loss_date = fake.date_between(FIRST_LOSS_DATE, LAST_LAWSUIT_LOSS_DATE)
        attorney_id = fake.random.choice(entities["normal_attorney_ids"])
        lawsuit = {"expert_id": fake.random.choice(entities["normal_expert_ids"]),
                   "filed_near_deadline": False, "demand_amount": None}
    else:
        loss_date = fake.date_between(FIRST_LOSS_DATE, LAST_LOSS_DATE)
        attorney_id = None
        if fake.random.random() < 0.4:
            attorney_id = fake.random.choice(entities["normal_attorney_ids"])
        lawsuit = None

    treatment_visits, medical_bill_amount = random_medical_amounts(fake)
    return {
        "group": group,
        "phone_number": None, "address_id": None, "last_name": None,
        "policy_id": None, "vehicle_id": None,
        "loss_date": loss_date,
        "loss_city": fake.random.choice(CITIES),
        "accident_type": fake.random.choice(ACCIDENT_TYPES),
        "injury_type": fake.random.choice(INJURY_TYPES),
        "repair_shop_id": fake.random.choice(entities["normal_repair_shop_ids"]),
        "clinic_id": fake.random.choice(entities["normal_clinic_ids"]),
        "attorney_id": attorney_id,
        "repair_estimate_amount": round(fake.random.uniform(1200, 9500), 2),
        "treatment_visits": treatment_visits,
        "medical_bill_amount": medical_bill_amount,
        "lawsuit": lawsuit,
    }


def plan_ring_a(fake, tables, entities, used_phone_numbers):
    """Ring A, staged accidents: shared phones and addresses, one repair shop,
    one city, a short time window and the same accident type."""
    ring_city = "Pasadena"
    shared_phone_numbers = []
    shared_address_ids = []
    for _ in range(3):
        shared_phone_numbers.append(new_phone_number(fake, used_phone_numbers))
        shared_address_ids.append(add_address(fake, tables, ring_city))

    plans = []
    for member_number in range(RING_A_SIZE):
        plan = plan_ordinary_claim(fake, entities, "ring_a", has_lawsuit=False)
        # 4 people share each phone and 4 share each address. The two groupings
        # cross each other, so all 12 claims form one connected group in the graph.
        plan["phone_number"] = shared_phone_numbers[member_number % 3]
        plan["address_id"] = shared_address_ids[member_number // 4]
        plan["repair_shop_id"] = entities["ring_a_repair_shop_id"]
        plan["loss_city"] = ring_city
        plan["loss_date"] = fake.date_between(datetime.date(2024, 3, 1), datetime.date(2024, 6, 30))
        plan["accident_type"] = "rear-end collision"
        plans.append(plan)
    return plans


def plan_ring_b(fake, entities):
    """Ring B, clinic and law firm mill: one clinic plus one law firm,
    the same injury, about the same visits and nearly the same bill."""
    plans = []
    for _ in range(RING_B_SIZE):
        plan = plan_ordinary_claim(fake, entities, "ring_b", has_lawsuit=False)
        plan["clinic_id"] = entities["ring_b_clinic_id"]
        plan["attorney_id"] = fake.random.choice(entities["ring_b_attorney_ids"])
        plan["injury_type"] = "neck and back strain"
        plan["treatment_visits"] = fake.random.randint(24, 26)
        plan["medical_bill_amount"] = round(fake.random.uniform(8300, 8700), 2)
        plans.append(plan)
    return plans


def plan_ring_c(fake, entities):
    """Ring C, litigation ring: every claim goes to a lawsuit with the same law
    firm and expert, filed just before the deadline, with similar demands."""
    plans = []
    for _ in range(RING_C_SIZE):
        plan = plan_ordinary_claim(fake, entities, "ring_c", has_lawsuit=True)
        plan["attorney_id"] = fake.random.choice(entities["ring_c_attorney_ids"])
        # Early losses only, so the 2-year deadline is before DATA_AS_OF_DATE.
        plan["loss_date"] = fake.date_between(datetime.date(2023, 1, 1), datetime.date(2024, 6, 30))
        plan["lawsuit"] = {
            "expert_id": entities["ring_c_expert_id"],
            "filed_near_deadline": True,
            "demand_amount": int(round(fake.random.uniform(73500, 76500), -2)),
        }
        plans.append(plan)
    return plans


def plan_families(fake, tables, entities, used_phone_numbers):
    """Innocent: family members in one car. They share a home, a phone,
    a policy and the vehicle, and they have the same loss date."""
    plans = []
    for family_number, family_size in enumerate(FAMILY_SIZES, start=1):
        driver_plan = plan_ordinary_claim(fake, entities, f"family_{family_number}", has_lawsuit=False)
        driver_plan["phone_number"] = new_phone_number(fake, used_phone_numbers)
        driver_plan["address_id"] = add_address(fake, tables, driver_plan["loss_city"])
        driver_plan["last_name"] = fake.last_name()
        driver_plan["policy_id"] = add_policy(fake, tables, driver_plan["loss_date"])
        driver_plan["vehicle_id"] = add_vehicle(fake, tables)
        plans.append(driver_plan)

        for _ in range(family_size - 1):
            passenger_plan = dict(driver_plan)  # a copy, so the driver plan stays unchanged
            # The car is repaired once, on the driver's claim.
            passenger_plan["repair_shop_id"] = None
            passenger_plan["repair_estimate_amount"] = None
            passenger_plan["injury_type"] = fake.random.choice(INJURY_TYPES)
            treatment_visits, medical_bill_amount = random_medical_amounts(fake)
            passenger_plan["treatment_visits"] = treatment_visits
            passenger_plan["medical_bill_amount"] = medical_bill_amount
            plans.append(passenger_plan)
    return plans


def plan_all_claims(fake, tables, entities, used_phone_numbers):
    """Return one plan for each of the TOTAL_CLAIMS claims (not yet shuffled)."""
    plans = []
    plans.extend(plan_ring_a(fake, tables, entities, used_phone_numbers))
    plans.extend(plan_ring_b(fake, entities))
    plans.extend(plan_ring_c(fake, entities))
    plans.extend(plan_families(fake, tables, entities, used_phone_numbers))

    # Innocent busy entities: many claims, but nothing else in common.
    for claim_number in range(BUSY_LAW_FIRM_CLAIMS):
        has_lawsuit = claim_number < BUSY_LAW_FIRM_LAWSUITS
        plan = plan_ordinary_claim(fake, entities, "busy_law_firm", has_lawsuit)
        plan["attorney_id"] = fake.random.choice(entities["busy_law_firm_attorney_ids"])
        plans.append(plan)
    for _ in range(POPULAR_REPAIR_SHOP_CLAIMS):
        plan = plan_ordinary_claim(fake, entities, "popular_repair_shop", has_lawsuit=False)
        plan["repair_shop_id"] = entities["popular_repair_shop_id"]
        plans.append(plan)
    for _ in range(LARGE_CLINIC_CLAIMS):
        plan = plan_ordinary_claim(fake, entities, "large_clinic", has_lawsuit=False)
        plan["clinic_id"] = entities["large_clinic_id"]
        plans.append(plan)

    background_claim_count = TOTAL_CLAIMS - len(plans)
    background_lawsuit_count = TOTAL_LAWSUITS - RING_C_SIZE - BUSY_LAW_FIRM_LAWSUITS
    for claim_number in range(background_claim_count):
        has_lawsuit = claim_number < background_lawsuit_count
        plans.append(plan_ordinary_claim(fake, entities, "background", has_lawsuit))
    return plans
