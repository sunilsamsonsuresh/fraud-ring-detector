"""Phase 1: plans for the planted fraud claims (PLAN-v2.md A4, config.FRAUD_PROFILES).

Each fraud claim shows each signal of its type with the chance in FRAUD_PROFILES.
Network signals become structure here: a shared phone or address (NL-1), a story group
(NL-4), the ring attorney (NL-3), the ring expert (NL-5), fewer occupants on the police
report than claimants (AS-6). Which network rules really fire is computed later from the
finished tables (network_truth.py), so the ground truth always matches the data.
"""

import datetime

from src import config
from src.datagen.plant_patterns import (
    GENERAL_LOSS_DATES, new_incident, new_person, new_plan, random_date,
)

RING_A_LOSS_DATES = (datetime.date(2024, 3, 1), datetime.date(2024, 8, 31))
# Ring C losses fall in one year, so the suits are filed within about 12 months of each other.
RING_C_LOSS_DATES = (datetime.date(2023, 7, 1), datetime.date(2024, 6, 30))
RING_A_CITY = "Pasadena"
LONE_FRAUD_TYPES = ["build_up", "billing_inflation", "coverage_trigger", "paper_accident"]


def decide_signals(fake, fraud_type):
    """The rule IDs this one claim shows, each with its own chance."""
    shown = set()
    for rule_id, chance in config.FRAUD_PROFILES[fraud_type].items():
        if fake.random.random() < chance:
            shown.add(rule_id)
    return shown


def split_into_incidents(claim_count):
    """Ring A cars hold 2 or 3 claimants. Example: 10 -> [3, 3, 2, 2]."""
    sizes = []
    remaining = claim_count
    while remaining > 0:
        size = 3 if remaining >= 5 or remaining == 3 else 2
        sizes.append(size)
        remaining -= size
    return sizes


def plan_ring_a(fake, world):
    """Staged accidents: cars with extra occupants, copied stories, shared phones and addresses,
    repair costs that grow. One hub person rides in three of the cars (a repeat claimant)."""
    hub = new_person(fake, world, RING_A_CITY)
    plans = []
    for incident_number, incident_size in enumerate(split_into_incidents(config.FRAUD_TYPE_SIZES["ring_a"])):
        incident = new_incident(fake, world, random_date(fake, RING_A_LOSS_DATES), RING_A_CITY,
                                "rear-end collision", has_police_report=True)
        extra_claimants = fake.random.random() < config.FRAUD_PROFILES["ring_a"]["AS-6"]
        incident["occupants_listed"] = incident_size - 1 if extra_claimants else incident_size
        driver = None
        for seat in range(incident_size):
            role = "driver" if seat == 0 else "passenger"
            signals = decide_signals(fake, "ring_a")
            signals.discard("AS-6")                      # decided once for the whole car above
            person = None
            if seat == 1 and incident_number < 3:
                person = hub
            elif "NL-1" in signals:
                # Alternate: the hub's phone or the hub's address.
                if len(plans) % 2 == 0:
                    person = new_person(fake, world, RING_A_CITY, phone_number=hub["phone_number"])
                else:
                    person = new_person(fake, world, RING_A_CITY, address=hub["address"])
            if role == "driver":
                plan = new_plan(fake, world, "ring_a", incident, role, person, fraud_type="ring_a")
                plan["repair_shop_id"] = world["ring_a_repair_shop_id"]
                driver = plan
            else:
                signals.discard("BF-4")                  # a passenger has no repair
                plan = new_plan(fake, world, "ring_a", incident, role, person, driver["policy"],
                                driver["vehicle"], fraud_type="ring_a")
            if extra_claimants:
                signals.add("AS-6")
            if "NL-4" in signals:
                plan["story_group"] = "ring_a"
            plan["signals"] = signals
            plans.append(plan)
    return plans


def plan_ring_b(fake, world):
    """Medical mill: one clinic and one attorney, heavy early treatment, medical build-up.
    The first two claims come from the same person (fraud claimants repeat more often)."""
    plans = []
    repeat_person = None
    for number in range(config.FRAUD_TYPE_SIZES["ring_b"]):
        incident = new_incident(fake, world, random_date(fake, GENERAL_LOSS_DATES))
        plan = new_plan(fake, world, "ring_b", incident, "driver", repeat_person, fraud_type="ring_b")
        if number == 0:
            repeat_person = plan["person"]
        elif number == 1:
            repeat_person = None
        plan["clinic_id"] = world["ring_b_clinic_id"]
        plan["injury_type"] = "neck and back strain"
        plan["signals"] = decide_signals(fake, "ring_b")
        plan["wants_attorney"] = True
        if "NL-3" in plan["signals"]:
            plan["attorney_id"] = world["ring_b_attorney_ids"][0]
        plans.append(plan)
    return plans


def plan_ring_c(fake, world):
    """Litigation ring: every claim is sued by one law firm with one expert, near the deadline,
    with copied wording."""
    plans = []
    for _ in range(config.FRAUD_TYPE_SIZES["ring_c"]):
        incident = new_incident(fake, world, random_date(fake, RING_C_LOSS_DATES))
        plan = new_plan(fake, world, "ring_c", incident, "driver", fraud_type="ring_c")
        plan["signals"] = decide_signals(fake, "ring_c")
        plan["has_lawsuit"] = True
        plan["attorney_id"] = fake.random.choice(world["ring_c_attorney_ids"])
        plan["demand_kind"] = "ring_c"
        if "NL-5" in plan["signals"]:
            plan["expert_id"] = world["ring_c_expert_id"]
        if "CT-7" in plan["signals"]:
            plan["lawsuit_kind"] = "near_deadline"
        if "NL-4" in plan["signals"]:
            plan["story_group"] = "ring_c"
        plans.append(plan)
    return plans


def plan_jump_in(fake, world):
    """A person who was not in the car claims injury. The real driver is an honest co-claimant."""
    plans = []
    for _ in range(config.FRAUD_TYPE_SIZES["jump_in"]):
        incident = new_incident(fake, world, random_date(fake, GENERAL_LOSS_DATES), has_police_report=True)
        driver = new_plan(fake, world, "jump_in_co_claimant", incident, "driver")
        jumper = new_plan(fake, world, "jump_in", incident, "passenger", None, driver["policy"],
                          driver["vehicle"], fraud_type="jump_in")
        jumper["signals"] = decide_signals(fake, "jump_in")
        # The police listed only the driver, so 2 claimants are more than 1 occupant.
        incident["occupants_listed"] = 1 if "AS-6" in jumper["signals"] else 2
        plans.extend([driver, jumper])
    return plans


def plan_lone_fraud(fake, world, fraud_type):
    """Build-up, billing inflation, coverage trigger, paper accident: one claim, no network."""
    plans = []
    for _ in range(config.FRAUD_TYPE_SIZES[fraud_type]):
        has_police_report = True if fraud_type == "paper_accident" else None
        incident = new_incident(fake, world, random_date(fake, GENERAL_LOSS_DATES),
                                has_police_report=has_police_report)
        plan = new_plan(fake, world, fraud_type, incident, "driver", fraud_type=fraud_type)
        plan["signals"] = decide_signals(fake, fraud_type)
        plans.append(plan)
    return plans


def plan_all_fraud(fake, world):
    plans = plan_ring_a(fake, world) + plan_ring_b(fake, world) + plan_ring_c(fake, world)
    plans.extend(plan_jump_in(fake, world))
    for fraud_type in LONE_FRAUD_TYPES:
        plans.extend(plan_lone_fraud(fake, world, fraud_type))
    return plans
