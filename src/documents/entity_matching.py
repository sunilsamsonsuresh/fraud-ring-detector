"""Match entities found in a PDF to nodes that already exist in the graph. Plain code, no LLM.

Order of the rules (PLAN.md, Step 6):
1. Exact match on a value that identifies one node: phone number, VIN, license plate,
   policy number, or the exact name of a repair shop, clinic, law firm, court,
   attorney or expert.
2. A claimant: the name, plus the date of birth or the phone number.
   Many people can have the same name, so a name alone is used only when exactly
   one claimant has it ("name only", the weakest method).
"""

from src.documents.value_parsing import normalize_code, normalize_phone, normalize_text, parse_date
from src.graph import queries

ID_PROPERTY_BY_LABEL = {
    "Phone": "number", "Address": "address_id", "Provider": "provider_id", "Attorney": "attorney_id",
    "LawFirm": "law_firm_id", "Expert": "expert_id", "Court": "court_id", "Vehicle": "vehicle_id",
    "Policy": "policy_id",
}
# entity type -> (lookup name, function that makes the lookup key)
EXACT_RULES = {
    "phone": ("phone", normalize_phone),
    "repair_shop": ("provider", normalize_text),
    "clinic": ("provider", normalize_text),
    "attorney": ("attorney", normalize_text),
    "law_firm": ("law_firm", normalize_text),
    "expert": ("expert", normalize_text),
    "court": ("court", normalize_text),
    "vin": ("vin", normalize_code),
    "license_plate": ("license_plate", normalize_code),
    "policy_number": ("policy_number", normalize_code),
}
MATCHABLE_TYPES = list(EXACT_RULES) + ["address", "claimant"]


def add_to_lookup(lookup, key, target):
    if key != "":
        lookup.setdefault(key, []).append(target)


def load_match_lookups(driver):
    """Read every matchable node once. Return {lookup name: {key: [target, ...]}}."""
    lookup_names = ["claimant", "address", "address_street", "phone", "provider", "attorney",
                    "law_firm", "expert", "court", "vin", "license_plate", "policy_number"]
    lookups = {name: {} for name in lookup_names}

    records, _, _ = driver.execute_query(queries.CLAIMANTS_FOR_MATCHING)
    for record in records:
        target = {"element_id": record["element_id"], "label": "Claimant", "node_id": record["node_id"],
                  "date_of_birth": record["date_of_birth"].to_native(),   # Neo4j date -> Python date
                  "phone_number": record["phone_number"] or ""}
        add_to_lookup(lookups["claimant"], normalize_text(record["name"]), target)

    records, _, _ = driver.execute_query(queries.NODES_FOR_MATCHING)
    for record in records:
        label, properties = record["label"], record["properties"]
        target = {"element_id": record["element_id"], "label": label,
                  "node_id": properties[ID_PROPERTY_BY_LABEL[label]]}
        if label == "Phone":
            add_to_lookup(lookups["phone"], normalize_phone(properties["number"]), target)
        elif label == "Address":
            street, city = normalize_text(properties["street"]), normalize_text(properties["city"])
            add_to_lookup(lookups["address"], f"{street}|{city}", target)
            add_to_lookup(lookups["address_street"], street, target)
        elif label == "Vehicle":
            add_to_lookup(lookups["vin"], normalize_code(properties.get("vin", "")), target)
            add_to_lookup(lookups["license_plate"], normalize_code(properties.get("license_plate", "")), target)
        elif label == "Policy":
            add_to_lookup(lookups["policy_number"], normalize_code(properties["policy_id"]), target)
        else:   # Provider, Attorney, LawFirm, Expert, Court: matched by name
            lookup_name = {"Provider": "provider", "Attorney": "attorney", "LawFirm": "law_firm",
                           "Expert": "expert", "Court": "court"}[label]
            add_to_lookup(lookups[lookup_name], normalize_text(properties["name"]), target)
    return lookups


def pick_one(targets, method):
    """Return (target, method, reason). Exactly one target is a match; none or many is not."""
    if len(targets) == 1:
        return targets[0], method, ""
    if not targets:
        return None, "", "no node in the graph has this value"
    return None, "", f"{len(targets)} nodes have this value"


def match_claimant(entity, lookups):
    candidates = lookups["claimant"].get(normalize_text(entity["value"]), [])
    if not candidates:
        return None, "", "no claimant has this name"
    date_of_birth = parse_date(entity.get("date_of_birth_text", ""))
    if date_of_birth is not None:
        same_birth_date = [c for c in candidates if c["date_of_birth"] == date_of_birth]
        if len(same_birth_date) == 1:
            return same_birth_date[0], "name + date of birth", ""
    phone = normalize_phone(entity.get("phone_text", ""))
    if phone:
        same_phone = [c for c in candidates if c["phone_number"] == phone]
        if len(same_phone) == 1:
            return same_phone[0], "name + phone", ""
    if len(candidates) == 1:
        return candidates[0], "name only", ""
    return None, "", f"{len(candidates)} claimants have this name; no date of birth or phone to choose"


def match_address(entity, lookups):
    street = normalize_text(entity["value"])
    city = normalize_text(entity.get("city", ""))
    if city:
        target, method, reason = pick_one(lookups["address"].get(f"{street}|{city}", []), "exact street + city")
        if target:
            return target, method, reason
    return pick_one(lookups["address_street"].get(street, []), "exact street")


def match_entity(entity, lookups):
    """Return (target or None, method, reason why not matched)."""
    entity_type = entity["entity_type"]
    if entity_type == "claimant":
        return match_claimant(entity, lookups)
    if entity_type == "address":
        return match_address(entity, lookups)
    lookup_name, make_key = EXACT_RULES[entity_type]
    return pick_one(lookups[lookup_name].get(make_key(entity["value"]), []), "exact")
