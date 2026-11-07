"""Turn one claim plan into table rows.

A claim plan (made in plant_patterns.py) says WHO and WHAT is in a claim:
which phone, shop, clinic, attorney, dates, amounts and lawsuit.
This file writes the rows: claimant, policy, vehicle, claim, payments,
lawsuit and settlement. Empty plan values (None) get a new row.
"""

from src.datagen.table_rows import (
    DATA_AS_OF_DATE, STATUTE_OF_LIMITATIONS_YEARS, add_address, add_claimant, add_days,
    add_policy, add_vehicle, add_years, find_row, make_id, new_phone_number,
)


def add_claim_rows(fake, tables, claim_id, plan, used_phone_numbers):
    phone_number = plan["phone_number"]
    if phone_number is None:
        phone_number = new_phone_number(fake, used_phone_numbers)

    address_id = plan["address_id"]
    if address_id is None:
        address_id = add_address(fake, tables, plan["loss_city"])

    last_name = plan["last_name"]
    if last_name is None:
        last_name = fake.last_name()

    policy_id = plan["policy_id"]
    if policy_id is None:
        policy_id = add_policy(fake, tables, plan["loss_date"])

    vehicle_id = plan["vehicle_id"]
    if vehicle_id is None:
        vehicle_id = add_vehicle(fake, tables)

    claimant_id = add_claimant(fake, tables, phone_number, address_id, last_name)

    if plan["lawsuit"] is not None:
        status = "in_litigation"
    else:
        status = fake.random.choice(["open", "closed", "closed"])

    claim_row = {
        "claim_id": claim_id,
        "claimant_id": claimant_id,
        "policy_id": policy_id,
        "vehicle_id": vehicle_id,
        "loss_date": plan["loss_date"],
        "reported_date": add_days(plan["loss_date"], fake.random.randint(0, 10)),
        "loss_city": plan["loss_city"],
        "accident_type": plan["accident_type"],
        "injury_type": plan["injury_type"],
        "repair_shop_id": plan["repair_shop_id"],
        "clinic_id": plan["clinic_id"],
        "attorney_id": plan["attorney_id"],
        "repair_estimate_amount": plan["repair_estimate_amount"],
        "treatment_visits": plan["treatment_visits"],
        "medical_bill_amount": plan["medical_bill_amount"],
        "status": status,
    }
    tables["claims"].append(claim_row)

    add_payments(fake, tables, claim_row)
    if plan["lawsuit"] is not None:
        add_lawsuit(fake, tables, claim_row, plan["lawsuit"])


def add_payments(fake, tables, claim_row):
    if claim_row["repair_shop_id"] is not None:
        shop = find_row(tables, "providers", "provider_id", claim_row["repair_shop_id"])
        tables["payments"].append({
            "payment_id": make_id(tables, "payments", "PAY"),
            "claim_id": claim_row["claim_id"],
            "payment_date": add_days(claim_row["loss_date"], fake.random.randint(15, 60)),
            "amount": claim_row["repair_estimate_amount"],
            "payment_type": "property_damage",
            "payee_name": shop["name"],
        })

    clinic = find_row(tables, "providers", "provider_id", claim_row["clinic_id"])
    tables["payments"].append({
        "payment_id": make_id(tables, "payments", "PAY"),
        "claim_id": claim_row["claim_id"],
        "payment_date": add_days(claim_row["loss_date"], fake.random.randint(30, 120)),
        "amount": claim_row["medical_bill_amount"],
        "payment_type": "medical",
        "payee_name": clinic["name"],
    })


def add_lawsuit(fake, tables, claim_row, lawsuit_plan):
    loss_date = claim_row["loss_date"]
    limitation_deadline = add_years(loss_date, STATUTE_OF_LIMITATIONS_YEARS)
    if lawsuit_plan["filed_near_deadline"]:
        filed_date = add_days(limitation_deadline, -fake.random.randint(1, 10))
    else:
        filed_date = add_days(loss_date, fake.random.randint(120, 540))

    demand_amount = lawsuit_plan["demand_amount"]
    if demand_amount is None:
        demand_amount = int(round(fake.random.uniform(25000, 250000), -3))

    # The plaintiff law firm is the firm of the claim's attorney, so the tables agree.
    attorney = find_row(tables, "attorneys", "attorney_id", claim_row["attorney_id"])
    lawsuit_id = make_id(tables, "lawsuits", "LS")

    settlement_date = add_days(filed_date, fake.random.randint(60, 300))
    wants_to_settle = fake.random.random() < 0.6
    is_settled = wants_to_settle and settlement_date <= DATA_AS_OF_DATE

    tables["lawsuits"].append({
        "lawsuit_id": lawsuit_id,
        "claim_id": claim_row["claim_id"],
        "court_id": fake.random.choice(tables["courts"])["court_id"],
        "plaintiff_law_firm_id": attorney["law_firm_id"],
        "expert_id": lawsuit_plan["expert_id"],
        "filed_date": filed_date,
        "limitation_deadline": limitation_deadline,
        "demand_amount": demand_amount,
        "status": "settled" if is_settled else "pending",
    })

    if is_settled:
        tables["settlements"].append({
            "settlement_id": make_id(tables, "settlements", "ST"),
            "lawsuit_id": lawsuit_id,
            "settlement_date": settlement_date,
            "settlement_amount": int(round(demand_amount * fake.random.uniform(0.35, 0.75), -2)),
        })
