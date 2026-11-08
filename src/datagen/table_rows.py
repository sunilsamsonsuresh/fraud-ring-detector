"""Small helpers that add rows and handle dates (v1, kept for v2).

v2 writes claimants, addresses, policies and vehicles in claim_rows.py (profile first).

`tables` is a dict: table name -> list of rows. A row is a dict: column -> value.
A new ID comes from the current row count, so IDs go 0001, 0002, ...

All randomness comes from `fake` (one seeded Faker object). Never use the
`random` module directly, or the same seed would no longer give the same data.
"""

import datetime

CITIES = ["Houston", "Pasadena", "Pearland", "Sugar Land", "Katy", "Baytown", "Conroe", "League City"]
STATE = "TX"
AREA_CODES = ["713", "281", "832", "346"]
COUNTIES = ["Harris", "Fort Bend", "Brazoria", "Galveston", "Montgomery"]
VEHICLE_MODELS = [
    ("Toyota", "Camry"), ("Honda", "Civic"), ("Ford", "F-150"), ("Chevrolet", "Malibu"),
    ("Nissan", "Altima"), ("Hyundai", "Elantra"), ("Kia", "Sorento"), ("Jeep", "Cherokee"),
]
# The data describes the world on this date. A fixed date (not "today")
# keeps the output the same on every run.
DATA_AS_OF_DATE = datetime.date(2026, 6, 30)


def make_id(tables, table_name, prefix):
    next_number = len(tables[table_name]) + 1
    return f"{prefix}-{next_number:04d}"


def add_days(start_date, days):
    return start_date + datetime.timedelta(days=days)


def add_years(start_date, years):
    try:
        return start_date.replace(year=start_date.year + years)
    except ValueError:
        # 29 February does not exist in most years. Use 28 February.
        return start_date.replace(year=start_date.year + years, day=28)


def find_row(tables, table_name, id_column, id_value):
    for row in tables[table_name]:
        if row[id_column] == id_value:
            return row
    raise KeyError(f"{id_value} not found in {table_name}")


def new_phone_number(fake, used_phone_numbers):
    """Return a phone number no one else has yet. Format: 713-555-0142."""
    while True:
        number = fake.random.choice(AREA_CODES) + "-555-" + fake.numerify("####")
        if number not in used_phone_numbers:
            used_phone_numbers.add(number)
            return number






def add_provider(fake, tables, provider_type, used_phone_numbers):
    if provider_type == "repair_shop":
        name_endings = ["Auto Body", "Collision Center", "Auto Repair"]
    else:
        name_endings = ["Chiropractic", "Spine & Injury Center", "Physical Therapy", "Medical Clinic"]
    existing_names = [row["name"] for row in tables["providers"]]
    while True:
        name = fake.last_name() + " " + fake.random.choice(name_endings)
        if name not in existing_names:
            break
    provider_id = make_id(tables, "providers", "PR")
    tables["providers"].append({
        "provider_id": provider_id, "name": name, "type": provider_type,
        "street": fake.street_address(), "city": fake.random.choice(CITIES), "state": STATE,
        "phone_number": new_phone_number(fake, used_phone_numbers),
    })
    return provider_id


def add_law_firm(fake, tables, attorney_count, used_phone_numbers):
    """Add one law firm and its attorneys. Return (law_firm_id, attorney_ids)."""
    law_firm_id = make_id(tables, "law_firms", "LF")
    name = f"{fake.last_name()} & {fake.last_name()} " + fake.random.choice(["Law Group", "Injury Lawyers", "LLP"])
    tables["law_firms"].append({
        "law_firm_id": law_firm_id, "name": name, "city": fake.random.choice(CITIES),
        "state": STATE, "phone_number": new_phone_number(fake, used_phone_numbers),
    })
    attorney_ids = []
    for _ in range(attorney_count):
        attorney_id = make_id(tables, "attorneys", "AT")
        tables["attorneys"].append({
            "attorney_id": attorney_id, "name": f"{fake.first_name()} {fake.last_name()}",
            "law_firm_id": law_firm_id,
        })
        attorney_ids.append(attorney_id)
    return law_firm_id, attorney_ids


def add_court(tables, county):
    court_id = make_id(tables, "courts", "CT")
    tables["courts"].append({
        "court_id": court_id, "name": f"{county} County District Court",
        "county": county, "state": STATE,
    })
    return court_id


def add_expert(fake, tables):
    specialties = ["orthopedic surgeon", "neurologist", "biomechanical engineer",
                   "accident reconstructionist", "pain management physician"]
    expert_id = make_id(tables, "experts", "EX")
    tables["experts"].append({
        "expert_id": expert_id, "name": f"{fake.first_name()} {fake.last_name()}",
        "specialty": fake.random.choice(specialties),
    })
    return expert_id
