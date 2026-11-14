"""The "world" and the building blocks of a claim plan.

A plan is a dict that says WHO and WHAT is in one claim: its group (fraud type, lookalike
group or "ordinary"), incident, person, policy, vehicle, repair shop, clinic, attorney,
lawsuit, story group and planted signals (rule IDs). Rows are written later
(write_claim_rows.py), after the plans are shuffled, so no ID gives away a group.

All randomness comes from `fake` (one seeded Faker object). Same seed, same plans.
"""

import datetime

from src.data_generation.table_row_helpers import (
    CITIES,
    COUNTIES,
    add_court,
    add_expert,
    add_law_firm,
    add_provider,
)

GENERAL_LOSS_DATES = (datetime.date(2023, 1, 1), datetime.date(2025, 6, 30))
# Lawsuit claims are older, so a suit can be filed (even near the 2-year deadline) before the data date.
LAWSUIT_LOSS_DATES = (datetime.date(2023, 1, 1), datetime.date(2024, 6, 30))
ACCIDENT_TYPES = [
    "rear-end collision",
    "side impact at intersection",
    "sideswipe while changing lanes",
    "parking lot collision",
    "low-speed head-on collision",
    "hit while turning left",
]
INJURY_TYPES = [
    "neck strain",
    "back strain",
    "neck and back strain",
    "shoulder injury",
    "knee injury",
    "concussion",
    "wrist fracture",
    "whiplash",
]
POLICE_REPORT_CHANCE = (
    0.8  # police do not always come; never to a parking lot collision
)
ATTORNEY_CHANCE = 0.4  # share of ordinary claimants who hire a lawyer
# Guards against links nobody planted. A claim fires NL-3 at 5 links and NL-5 at 3 lawsuits,
# so an honest (clinic, attorney) pair may join at most 3 claims of other incidents, and an
# honest (law firm, expert) pair at most 2 lawsuits of other incidents.
MAX_HONEST_CLINIC_ATTORNEY_LINKS = 3
MAX_HONEST_FIRM_EXPERT_LINKS = 2


def make_world(fake, tables):
    """Add courts, experts, providers and law firms. Return the world dict with the role of each.
    Roles are shuffled first, so a special shop or firm does not get a give-away ID."""
    world = {
        "incidents": [],
        "persons": [],
        "addresses": [],
        "policies": [],
        "vehicles": [],
        "clinic_attorney_claims": {},
        "firm_expert_claims": {},
        "used_phone_numbers": set(),
    }
    for county in COUNTIES:
        add_court(tables, county)
    world["normal_expert_ids"] = []
    for role in shuffled(fake, ["normal"] * 12 + ["ring_c", "nl5_noise"]):
        expert_id = add_expert(fake, tables)
        if role == "normal":
            world["normal_expert_ids"].append(expert_id)
        else:
            world[f"{role}_expert_id"] = expert_id
    world["normal_repair_shop_ids"] = []
    for role in shuffled(fake, ["normal"] * 40 + ["ring_a", "busy"]):
        shop_id = add_provider(fake, tables, "repair_shop", world["used_phone_numbers"])
        if role == "normal":
            world["normal_repair_shop_ids"].append(shop_id)
        else:
            world[f"{role}_repair_shop_id"] = shop_id
    world["normal_clinic_ids"] = []
    for role in shuffled(fake, ["normal"] * 30 + ["ring_b", "large"]):
        clinic_id = add_provider(fake, tables, "clinic", world["used_phone_numbers"])
        if role == "normal":
            world["normal_clinic_ids"].append(clinic_id)
        else:
            world[f"{role}_clinic_id"] = clinic_id
    world["normal_attorney_ids"] = []
    world["normal_law_firms"] = []  # [(law_firm_id, attorney_ids)]
    # "referral": one honest attorney who sends all clients to one clinic (NL-3 base-rate noise).
    for role in shuffled(
        fake, ["normal"] * 14 + ["busy", "ring_b", "ring_c", "referral"]
    ):
        attorney_count = {
            "normal": fake.random.randint(1, 3),
            "busy": 5,
            "ring_b": 1,
            "ring_c": 2,
            "referral": 1,
        }[role]
        law_firm_id, attorney_ids = add_law_firm(
            fake, tables, attorney_count, world["used_phone_numbers"]
        )
        if role == "normal":
            world["normal_attorney_ids"].extend(attorney_ids)
            world["normal_law_firms"].append((law_firm_id, attorney_ids))
        else:
            world[f"{role}_law_firm_id"] = law_firm_id
            world[f"{role}_attorney_ids"] = attorney_ids
    return world


def shuffled(fake, items):
    items = list(items)
    fake.random.shuffle(items)
    return items


def random_date(fake, date_range):
    return fake.date_between(date_range[0], date_range[1])


def new_incident(
    fake, world, loss_date, city=None, accident_type=None, has_police_report=None
):
    if city is None:
        city = fake.random.choice(CITIES)
    if accident_type is None:
        accident_type = fake.random.choice(ACCIDENT_TYPES)
    if has_police_report is None:
        has_police_report = (
            accident_type != "parking lot collision"
            and fake.random.random() < POLICE_REPORT_CHANCE
        )
    incident = {
        "key": len(world["incidents"]),
        "loss_date": loss_date,
        "city": city,
        "accident_type": accident_type,
        "has_police_report": has_police_report,
        "location_text": f"{fake.street_name()} and {fake.street_name()}, {city}",
        "occupants_listed": None,
    }
    world["incidents"].append(incident)
    return incident


def new_person(fake, world, city, phone_number=None, address=None, last_name=None):
    if address is None:
        address = {
            "key": len(world["addresses"]),
            "street": fake.street_address(),
            "city": city,
            "zip_code": fake.zipcode_in_state("TX"),
        }
        world["addresses"].append(address)
    if phone_number is None:
        phone_number = new_phone_number(fake, world)
    person = {
        "key": len(world["persons"]),
        "first_name": fake.first_name(),
        "last_name": last_name or fake.last_name(),
        "date_of_birth": fake.date_between(
            datetime.date(1950, 1, 1), datetime.date(2004, 12, 31)
        ),
        "phone_number": phone_number,
        "address": address,
    }
    world["persons"].append(person)
    return person


def new_phone_number(fake, world):
    """A phone number nobody has yet. Format: 713-555-0142."""
    while True:
        number = (
            fake.random.choice(["713", "281", "832", "346"])
            + "-555-"
            + fake.numerify("####")
        )
        if number not in world["used_phone_numbers"]:
            world["used_phone_numbers"].add(number)
            return number


def new_record(world, kind):
    """A new policy or vehicle. Its row (and ID) is written later."""
    record = {"key": len(world[kind])}
    world[kind].append(record)
    return record


def new_plan(
    fake,
    world,
    group,
    incident,
    role,
    person=None,
    policy=None,
    vehicle=None,
    fraud_type=None,
):
    """One claim plan. A driver gets a repair shop; a passenger rides in the driver's car."""
    if person is None:
        person = new_person(fake, world, incident["city"])
    return {
        "group": group,
        "fraud_type": fraud_type,
        "is_fraud": fraud_type is not None,
        "incident": incident,
        "role": role,
        "person": person,
        "policy": policy if policy is not None else new_record(world, "policies"),
        "vehicle": vehicle if vehicle is not None else new_record(world, "vehicles"),
        "repair_shop_id": fake.random.choice(world["normal_repair_shop_ids"])
        if role == "driver"
        else None,
        "repair_estimate_amount": round(fake.random.uniform(1200, 9500), 2)
        if role == "driver"
        else None,
        "clinic_id": None,
        "attorney_id": None,
        "wants_attorney": fake.random.random() < ATTORNEY_CHANCE,
        "has_lawsuit": False,
        "expert_id": None,
        "lawsuit_kind": "normal",
        "injury_type": fake.random.choice(INJURY_TYPES),
        "story_group": None,
        "signals": set(),
        "tags": set(),
    }


def pair_is_safe(claims_by_incident, incident_key, max_links):
    """True if one more claim of `incident_key` keeps every claim at max_links or fewer links
    to claims of OTHER incidents. claims_by_incident: {incident key: claim count}."""
    counts = dict(claims_by_incident)
    counts[incident_key] = counts.get(incident_key, 0) + 1
    total = sum(counts.values())
    for count in counts.values():
        if total - count > max_links:
            return False
    return True


def register_pair(world, kind, pair, incident_key):
    usage = world[kind].setdefault(pair, {})
    usage[incident_key] = usage.get(incident_key, 0) + 1


def choose_guarded(fake, world, kind, first_id, candidate_ids, incident_key, max_links):
    """Pick a second partner (attorney or expert) whose pair with first_id stays safe."""
    allowed = []
    for candidate_id in candidate_ids:
        if pair_is_safe(
            world[kind].get((first_id, candidate_id), {}), incident_key, max_links
        ):
            allowed.append(candidate_id)
    chosen_id = fake.random.choice(allowed)
    register_pair(world, kind, (first_id, chosen_id), incident_key)
    return chosen_id


def assign_partners(fake, world, plans):
    """Give every plan without one a clinic, an attorney (if wanted or sued) and an expert (if sued).

    Pass 1 registers the pairs that the planners set on purpose (rings, noise groups, honest
    multi-claimant incidents). Pass 2 fills the rest with guarded choices, so an honest claim
    never joins a planted pair, and honest pairs stay below the NL-3 and NL-5 limits."""
    for plan in plans:
        if plan["clinic_id"] is not None and plan["attorney_id"] is not None:
            register_pair(
                world,
                "clinic_attorney_claims",
                (plan["clinic_id"], plan["attorney_id"]),
                plan["incident"]["key"],
            )
        if (
            plan["has_lawsuit"]
            and plan["attorney_id"] is not None
            and plan["expert_id"] is not None
        ):
            register_pair(
                world,
                "firm_expert_claims",
                (law_firm_of(world, plan["attorney_id"]), plan["expert_id"]),
                plan["incident"]["key"],
            )
    for plan in plans:
        incident_key = plan["incident"]["key"]
        clinic_was_missing = plan["clinic_id"] is None
        if clinic_was_missing:
            plan["clinic_id"] = fake.random.choice(world["normal_clinic_ids"])
        needs_attorney = plan["has_lawsuit"] or plan["wants_attorney"]
        if plan["attorney_id"] is None and needs_attorney:
            candidates = plan.get("attorney_candidates", world["normal_attorney_ids"])
            plan["attorney_id"] = choose_guarded(
                fake,
                world,
                "clinic_attorney_claims",
                plan["clinic_id"],
                candidates,
                incident_key,
                MAX_HONEST_CLINIC_ATTORNEY_LINKS,
            )
        elif plan["attorney_id"] is not None and clinic_was_missing:
            register_pair(
                world,
                "clinic_attorney_claims",
                (plan["clinic_id"], plan["attorney_id"]),
                incident_key,
            )
        if plan["has_lawsuit"] and plan["expert_id"] is None:
            firm_id = law_firm_of(world, plan["attorney_id"])
            plan["expert_id"] = choose_guarded(
                fake,
                world,
                "firm_expert_claims",
                firm_id,
                world["normal_expert_ids"],
                incident_key,
                MAX_HONEST_FIRM_EXPERT_LINKS,
            )


def law_firm_of(world, attorney_id):
    for law_firm_id, attorney_ids in world["normal_law_firms"]:
        if attorney_id in attorney_ids:
            return law_firm_id
    for role in ["busy", "ring_b", "ring_c", "referral"]:
        if attorney_id in world[f"{role}_attorney_ids"]:
            return world[f"{role}_law_firm_id"]
    raise KeyError(attorney_id)


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.claim_plan_blocks      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    from faker import Faker

    from src.data_generation.generate_tables import TABLE_NAMES

    fake = Faker("en_US")
    fake.seed_instance(42)
    tables = {table_name: [] for table_name in TABLE_NAMES}

    # Step 1: make_world -> courts, experts, shops, clinics and law firms. Some get a special role.
    world = make_world(fake, tables)
    print(
        "1. make_world: providers",
        len(tables["providers"]),
        "| law firms",
        len(tables["law_firms"]),
        "| ring B clinic",
        world["ring_b_clinic_id"],
    )

    # Step 2: one incident, one person, one plan. This is a claim before any row is written.
    incident = new_incident(fake, world, random_date(fake, GENERAL_LOSS_DATES))
    plan = new_plan(fake, world, "ordinary", incident, "driver")
    print(
        "2. new_plan: group",
        plan["group"],
        "| role",
        plan["role"],
        "| city",
        incident["city"],
        "| person",
        plan["person"]["first_name"],
        plan["person"]["last_name"],
    )

    # Step 3: the guard against links nobody planted. A pair may join at most 3 claims of other incidents.
    print(
        "3. pair_is_safe: a 4th incident on the pair ->",
        pair_is_safe({1: 1, 2: 1, 3: 1}, 4, 3),
        "| a 5th incident on the pair ->",
        pair_is_safe({1: 1, 2: 1, 3: 1, 4: 1}, 5, 3),
    )
