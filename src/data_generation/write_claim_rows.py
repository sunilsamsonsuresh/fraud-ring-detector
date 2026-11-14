"""Turn the shuffled plans into table rows.

For each claim: its incident, claimant, address, policy and vehicle rows (once each), the
claim row, the treatment visits, the payments, the reserve history and the lawsuit.
The planted table rules (BI-5, BI-6, BF-1 to BF-4, CT-4) decide the dates and amounts.
Honest values keep a safe distance from every threshold in config.py:
  BI-6  honest visits are 3+ days apart, so at most 11 fall in the first 30 days (fires at 13)
  BF-1  honest reserve changes are 35+ days apart and grow at most 30% (fires above 50% in 30 days)
  BF-2  honest payments stay below the reserve (fires at 1.5 times)
  BF-3  honest payments are 15+ days apart (fires at 3 within 14 days)
  BF-4  honest repair payments are at most 1.25 times the estimate (fires at 1.5)
  CT-4  honest claims are reported within 14 days (fires above 30)
"""

from src.data_generation.table_row_helpers import (
    DATA_AS_OF_DATE,
    STATE,
    VEHICLE_MODELS,
    add_days,
    find_row,
    make_id,
)
from src.data_generation.write_policy_and_lawsuit_rows import (
    add_lawsuit_rows,
    add_policy_row,
)

FIRST_CLAIM_NUMBER = 1001
# procedure group -> (lowest charge, highest charge)
PROCEDURE_CHARGES = {
    "evaluation": (250, 400),
    "chiropractic adjustment": (80, 150),
    "physical therapy": (120, 220),
    "massage therapy": (70, 120),
    "imaging": (400, 1200),
    "pain management": (300, 700),
}
EXPENSE_PAYEES = [
    "Gulf Coast Appraisal Services",
    "Lone Star Records Retrieval",
    "Bayou Independent Adjusters",
]


def write_all_rows(fake, tables, plans):
    """Give each plan its claim ID (in shuffled order) and write all of its rows."""
    plans_by_policy = {}
    for plan in plans:
        plans_by_policy.setdefault(plan["policy"]["key"], []).append(plan)
    ids = {
        "incidents": {},
        "addresses": {},
        "persons": {},
        "policies": {},
        "vehicles": {},
    }
    for position, plan in enumerate(plans):
        plan["claim_id"] = f"C-{FIRST_CLAIM_NUMBER + position}"
        incident = plan["incident"]
        if incident["key"] not in ids["incidents"]:
            ids["incidents"][incident["key"]] = make_id(tables, "incidents", "I")
            tables["incidents"].append(
                {
                    "incident_id": ids["incidents"][incident["key"]],
                    "loss_date": incident["loss_date"],
                    "location_text": incident["location_text"],
                }
            )
        claimant_id = claimant_id_of(tables, ids, plan["person"])
        if plan["policy"]["key"] not in ids["policies"]:
            ids["policies"][plan["policy"]["key"]] = add_policy_row(
                fake, tables, plans_by_policy[plan["policy"]["key"]]
            )
        if plan["vehicle"]["key"] not in ids["vehicles"]:
            ids["vehicles"][plan["vehicle"]["key"]] = add_vehicle_row(fake, tables)
        add_claim_rows(
            fake,
            tables,
            plan,
            claimant_id,
            ids["incidents"][incident["key"]],
            ids["policies"][plan["policy"]["key"]],
            ids["vehicles"][plan["vehicle"]["key"]],
        )


def claimant_id_of(tables, ids, person):
    address = person["address"]
    if address["key"] not in ids["addresses"]:
        ids["addresses"][address["key"]] = make_id(tables, "addresses", "A")
        tables["addresses"].append(
            {
                "address_id": ids["addresses"][address["key"]],
                "street": address["street"],
                "city": address["city"],
                "state": STATE,
                "zip_code": address["zip_code"],
            }
        )
    if person["key"] not in ids["persons"]:
        ids["persons"][person["key"]] = make_id(tables, "claimants", "CL")
        tables["claimants"].append(
            {
                "claimant_id": ids["persons"][person["key"]],
                "first_name": person["first_name"],
                "last_name": person["last_name"],
                "date_of_birth": person["date_of_birth"],
                "phone_number": person["phone_number"],
                "address_id": ids["addresses"][address["key"]],
            }
        )
    return ids["persons"][person["key"]]


def add_vehicle_row(fake, tables):
    make, model = fake.random.choice(VEHICLE_MODELS)
    vehicle_id = make_id(tables, "vehicles", "V")
    tables["vehicles"].append(
        {
            "vehicle_id": vehicle_id,
            "vin": fake.vin(),
            "year": fake.random.randint(2010, 2024),
            "make": make,
            "model": model,
            "license_plate": fake.license_plate(),
        }
    )
    return vehicle_id


def visit_offsets(fake, plan, first_offset):
    """Days after the loss of each visit. BI-6 packs 13 to 18 visits into days first..28."""
    signals = plan["signals"]
    offsets = []
    if "BI-6" in signals:
        offsets = sorted(
            fake.random.sample(
                range(max(first_offset, 1), 29), fake.random.randint(13, 18)
            )
        )
        later_visits = (
            fake.random.randint(15, 30)
            if "BI-2" in signals or plan["group"] == "serious_injury"
            else fake.random.randint(0, 10)
        )
        day = 31
    else:
        later_visits = (
            fake.random.randint(28, 45)
            if "BI-2" in signals
            else fake.random.randint(2, 30)
        )
        day = first_offset
    for _ in range(later_visits):
        offsets.append(day)
        day += fake.random.randint(3, 10)
    return offsets


def add_treatments(fake, tables, plan, claim_id, loss_date):
    """Visits at the claim's clinic. Return (first visit date, visit count, total charge, attorney retained date)."""
    attorney_offset = None
    if plan["attorney_id"] is not None and "BI-5" in plan["signals"]:
        attorney_offset = fake.random.randint(0, 2)
        first_offset = attorney_offset + fake.random.randint(2, 7)
    else:
        first_offset = (
            fake.random.randint(0, 3)
            if "BI-6" in plan["signals"]
            else fake.random.randint(0, 7)
        )
    total_charge = 0.0
    visit_dates = []
    for number, offset in enumerate(visit_offsets(fake, plan, first_offset)):
        visit_date = add_days(loss_date, offset)
        if visit_date > DATA_AS_OF_DATE:
            break
        group = (
            "evaluation"
            if number == 0
            else fake.random.choice(list(PROCEDURE_CHARGES)[1:])
        )
        low, high = PROCEDURE_CHARGES[group]
        charge = round(fake.random.uniform(low, high), 2)
        total_charge += charge
        visit_dates.append(visit_date)
        tables["treatments"].append(
            {
                "treatment_id": make_id(tables, "treatments", "TR"),
                "claim_id": claim_id,
                "provider_id": plan["clinic_id"],
                "visit_date": visit_date,
                "procedure_group": group,
                "charge": charge,
            }
        )
    retained_date = None
    if plan["attorney_id"] is not None:
        if attorney_offset is not None:
            retained_date = add_days(loss_date, attorney_offset)
        else:
            retained_date = add_days(visit_dates[0], fake.random.randint(5, 60))
    return visit_dates[0], len(visit_dates), round(total_charge, 2), retained_date


def payment_items(fake, tables, plan, claim_row, person_name):
    """[(amount, type, payee)] for the honest-spaced payments, and the BF-3 cluster (or [])."""
    items, cluster = [], []
    if plan["repair_shop_id"] is not None:
        factor = (
            fake.random.uniform(1.6, 2.4)
            if "BF-4" in plan["signals"]
            else fake.random.uniform(0.95, 1.25)
        )
        shop = find_row(tables, "providers", "provider_id", plan["repair_shop_id"])
        items.append(
            (
                round(claim_row["repair_estimate_amount"] * factor, 2),
                "repair",
                shop["name"],
            )
        )
    clinic = find_row(tables, "providers", "provider_id", plan["clinic_id"])
    medical = claim_row["medical_bill_amount"]
    if "BF-3" in plan["signals"]:
        thirds = [round(medical / 3, 2), round(medical / 3, 2)]
        cluster = [
            (amount, "medical", clinic["name"])
            for amount in thirds + [round(medical - sum(thirds), 2)]
        ]
    elif fake.random.random() < 0.5:
        half = round(medical / 2, 2)
        items.extend(
            [
                (half, "medical", clinic["name"]),
                (round(medical - half, 2), "medical", clinic["name"]),
            ]
        )
    else:
        items.append((medical, "medical", clinic["name"]))
    if fake.random.random() < 0.3:
        items.append(
            (round(fake.random.uniform(1000, 15000), 2), "indemnity", person_name)
        )
    if fake.random.random() < 0.2:
        items.append(
            (
                round(fake.random.uniform(150, 1500), 2),
                "expense",
                fake.random.choice(EXPENSE_PAYEES),
            )
        )
    return items, cluster


def add_payments(fake, tables, plan, claim_row, person_name):
    """Honest payments are 15 to 45 days apart. BF-3 adds 3 medical payments within 12 days."""
    items, cluster = payment_items(fake, tables, plan, claim_row, person_name)
    payment_date = add_days(claim_row["reported_date"], fake.random.randint(10, 30))
    dated = []
    for item in items:
        dated.append((payment_date, item))
        payment_date = add_days(payment_date, fake.random.randint(15, 45))
    cluster_offsets = [0, fake.random.randint(2, 5)]
    cluster_offsets.append(cluster_offsets[1] + fake.random.randint(2, 7))
    for offset, item in zip(cluster_offsets, cluster):
        dated.append((add_days(payment_date, offset), item))
    for date_paid, (amount, payment_type, payee) in dated:
        tables["payments"].append(
            {
                "payment_id": make_id(tables, "payments", "PAY"),
                "claim_id": claim_row["claim_id"],
                "payment_date": date_paid,
                "amount": amount,
                "payment_type": payment_type,
                "payee_name": payee,
            }
        )
    return round(sum(item[0] for _, item in dated), 2), max(
        date_paid for date_paid, _ in dated
    )


def add_reserve_events(fake, tables, plan, claim_id, reported_date, total_paid):
    """The reserve history. It ends at a final reserve above the payments (BF-2: far below them)."""
    if "BF-2" in plan["signals"]:
        final_reserve = total_paid / fake.random.uniform(1.6, 2.5)
    else:
        final_reserve = total_paid * fake.random.uniform(1.05, 1.4)
    dates, factors = [reported_date], []
    if "BF-1" in plan["signals"]:
        dates.append(add_days(reported_date, fake.random.randint(10, 25)))
        factors.append(fake.random.uniform(1.7, 2.6))
    for _ in range(fake.random.randint(1, 3)):
        next_date = add_days(dates[-1], fake.random.randint(35, 90))
        if next_date > DATA_AS_OF_DATE:
            break
        dates.append(next_date)
        factors.append(fake.random.uniform(0.85, 1.3))
    reserve = final_reserve
    for factor in factors:
        reserve = reserve / factor  # walk back from the final reserve to the first one
    for index, event_date in enumerate(dates):
        if index > 0:
            reserve = reserve * factors[index - 1]
        tables["reserve_events"].append(
            {
                "event_id": make_id(tables, "reserve_events", "RE"),
                "claim_id": claim_id,
                "event_date": event_date,
                "reserve_total": round(reserve, 2),
            }
        )
    return dates[-1]


def add_claim_rows(fake, tables, plan, claimant_id, incident_id, policy_id, vehicle_id):
    loss_date = plan["incident"]["loss_date"]
    late = "CT-4" in plan["signals"]
    reported_date = add_days(
        loss_date, fake.random.randint(35, 120) if late else fake.random.randint(0, 14)
    )
    first_visit, visit_count, medical_total, retained_date = add_treatments(
        fake, tables, plan, plan["claim_id"], loss_date
    )
    claim_row = {
        "claim_id": plan["claim_id"],
        "claimant_id": claimant_id,
        "policy_id": policy_id,
        "vehicle_id": vehicle_id,
        "incident_id": incident_id,
        "loss_date": loss_date,
        "reported_date": reported_date,
        "close_date": None,
        "status": "open",
        "loss_city": plan["incident"]["city"],
        "accident_type": plan["incident"]["accident_type"],
        "injury_type": plan["injury_type"],
        "repair_shop_id": plan["repair_shop_id"],
        "clinic_id": plan["clinic_id"],
        "attorney_id": plan["attorney_id"],
        "attorney_retained_date": retained_date,
        "repair_estimate_amount": plan["repair_estimate_amount"],
        "treatment_visits": visit_count,
        "medical_bill_amount": medical_total,
    }
    tables["claims"].append(claim_row)
    person = plan["person"]
    total_paid, last_payment = add_payments(
        fake, tables, plan, claim_row, f"{person['first_name']} {person['last_name']}"
    )
    last_reserve = add_reserve_events(
        fake, tables, plan, plan["claim_id"], reported_date, total_paid
    )
    last_activity = max(last_payment, last_reserve, first_visit)
    if plan["has_lawsuit"]:
        attorney = find_row(tables, "attorneys", "attorney_id", plan["attorney_id"])
        _, settled_on = add_lawsuit_rows(
            fake, tables, plan, claim_row, attorney["law_firm_id"]
        )
        claim_row["status"] = "in_litigation"
        if settled_on is not None and add_days(settled_on, 30) <= DATA_AS_OF_DATE:
            claim_row["status"], claim_row["close_date"] = (
                "closed",
                add_days(settled_on, fake.random.randint(10, 30)),
            )
    elif add_days(last_activity, 30) <= DATA_AS_OF_DATE and fake.random.random() < 0.8:
        claim_row["status"], claim_row["close_date"] = (
            "closed",
            add_days(last_activity, fake.random.randint(10, 30)),
        )


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.write_claim_rows      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    from faker import Faker

    fake = Faker("en_US")
    fake.seed_instance(42)
    # Rule BI-6 (heavy early treatment) packs 13 to 18 visits into the first 28 days.
    plan = {"signals": {"BI-6"}, "group": "ring_b"}
    offsets = visit_offsets(fake, plan, first_offset=1)
    print(
        "1. visit_offsets with BI-6: days of the visits in the first 28 days:",
        [day for day in offsets if day <= 28],
    )
    print(
        "   visits in the first 30 days:",
        len([day for day in offsets if day <= 30]),
        "(rule BI-6 fires above 12)",
    )
    plan = {"signals": set(), "group": "ordinary"}
    offsets = visit_offsets(fake, plan, first_offset=2)
    print(
        "2. visit_offsets, honest claim: visits in the first 30 days:",
        len([day for day in offsets if day <= 30]),
    )
