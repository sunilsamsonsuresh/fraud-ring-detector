"""Planted signals and feature values.

1. Base-rate noise: for each non-network rule, EXACTLY round(rate x population) ordinary
   claims get the rule. The population is the ordinary claims where the rule can apply.
   Exact counts (not a coin toss per claim) make the honest rate equal the target.
2. Feature values: a planted rule gets a firing rating (for example BI-1 -> "Inconsistent").
   Every other feature gets a harmless rating, sometimes a middle one ("Elevated", "Possible").
   The PDFs carry these values in prose.
"""

from src import config
from src.data_loading.finding_features import FEATURES
from src.scoring.rules_catalog import RULES

# Network rules come from structure (plan_fraud_claims.py, plan_honest_claims.py) and are computed from the tables (compute_network_truth.py).
STRUCTURAL_RULES = ["AS-6", "NL-1", "NL-2", "NL-3", "NL-4", "NL-5", "NL-6"]
POLICY_RULES = ["CT-1", "CT-2", "CT-3"]

# rule ID -> [(rating that fires the rule, weight)]
FIRING_VALUES = {
    "BI-1": ("injury_crash_fit", [("Inconsistent", 1)]),
    "BI-2": ("treatment_growth", [("Disproportionate", 3), ("Extreme", 2)]),
    "BI-3": (
        "objective_support",
        [("Predominantly subjective", 3), ("Contradicted", 1)],
    ),
    "BI-4": ("pre_existing_condition", [("Material", 7), ("Predominant", 3)]),
    "AS-1": ("occurrence_support", [("Uncorroborated", 1)]),
    "AS-2": ("occurrence_support", [("Contradicted", 3), ("Suspected staged", 2)]),
    "AS-3": ("damage_crash_fit", [("Inconsistent", 1)]),
    "AS-4": ("account_stability", [("Materially changed", 1)]),
    "AS-5": ("occupant_presence", [("Added later", 1), ("Not present", 1)]),
    "BF-5": ("duplicate_billing", [("Confirmed", 1)]),
    "BF-6": ("labor_hours_plausibility", [("Excessive", 1)]),
    "CT-6": ("driver_status", [("Unlisted", 3), ("Excluded", 2)]),
}
# feature -> [(harmless rating, weight)]
HARMLESS_VALUES = {
    "injury_crash_fit": [("Strong", 6), ("Reasonable", 3), ("Unclear", 1)],
    "treatment_growth": [("Normal", 3), ("Elevated", 1)],
    "objective_support": [("Strong", 1), ("Partial", 1)],
    "pre_existing_condition": [("None", 4), ("Minor", 1)],
    "occurrence_support": [("Confirmed", 3), ("Partially corroborated", 2)],
    "damage_crash_fit": [("Strong", 6), ("Reasonable", 3), ("Unclear", 1)],
    "account_stability": [("Stable", 4), ("Clarified", 1)],
    "occupant_presence": [("Verified", 9), ("Unclear", 1)],
    "duplicate_billing": [("None", 6), ("Possible", 1)],
    "labor_hours_plausibility": [("Plausible", 4), ("Elevated", 1)],
    "prior_damage_evidence": [("None", 6), ("Possible", 1)],
    "known_loss_evidence": [("Weak", 9), ("Moderate", 1)],
    "driver_status": [("Listed", 6), ("Household", 1)],
}


def weighted_choice(fake, options):
    total = sum(weight for _, weight in options)
    point = fake.random.random() * total
    for value, weight in options:
        point -= weight
        if point < 0:
            return value
    return options[-1][0]


def rule_applies(rule_id, plan):
    """Can this rule fire for this claim at all? Used for the noise population."""
    if rule_id == "BI-5":
        return plan["attorney_id"] is not None
    if rule_id in ["BF-4", "BF-6"]:
        return plan["repair_shop_id"] is not None
    if rule_id in ["AS-6", "AS-7"]:
        return plan["incident"]["has_police_report"]
    if rule_id in ["CT-7", "NL-5"]:
        return plan["has_lawsuit"]
    return True


def add_base_rate_noise(fake, ordinary_plans):
    """Give EXACTLY round(rate x population) ordinary claims each non-network rule."""
    policy_users = {}
    for plan in ordinary_plans:
        policy_users[plan["policy"]["key"]] = (
            policy_users.get(plan["policy"]["key"], 0) + 1
        )
    for rule in RULES:
        if rule.rule_id in STRUCTURAL_RULES:
            continue
        population = [
            plan for plan in ordinary_plans if rule_applies(rule.rule_id, plan)
        ]
        eligible = []
        for plan in population:
            if rule.rule_id in POLICY_RULES and (
                policy_users[plan["policy"]["key"]] > 1 or plan["tags"]
            ):
                continue  # policy dates are shared: change only a policy of one plain claim
            if rule.rule_id == "CT-7" and plan["tags"]:
                continue  # moving a planted suit group's filing date would break its network noise
            if rule.rule_id == "AS-1" and "AS-2" in plan["signals"]:
                continue  # one feature (occurrence_support) cannot give both ratings
            eligible.append(plan)
        count = round(config.HONEST_RULE_RATES[rule.rule_id] * len(population))
        for plan in fake.random.sample(eligible, count):
            plan["signals"].add(rule.rule_id)


def feature_applies(feature, plan):
    if feature.code == "occupants_listed":
        return plan["incident"]["has_police_report"]
    if feature.code == "labor_hours_plausibility":
        return plan["repair_shop_id"] is not None
    return True


def choose_features(fake, plan):
    """{feature code: value} for one claim, from its planted signals."""
    features = {}
    for feature in FEATURES:
        if not feature_applies(feature, plan):
            continue
        if feature.code == "occupants_listed":
            features[feature.code] = plan["incident"]["occupants_listed"]
        else:
            features[feature.code] = weighted_choice(
                fake, HARMLESS_VALUES[feature.code]
            )
    for rule_id, (feature_code, options) in FIRING_VALUES.items():
        if rule_id in plan["signals"] and feature_code in features:
            features[feature_code] = weighted_choice(fake, options)
    if "CT-5" in plan["signals"]:
        # Prior damage shown as new: documented prior damage, or strong proof the loss was known.
        if fake.random.random() < 0.75:
            features["prior_damage_evidence"] = weighted_choice(
                fake, [("Documented", 3), ("Material", 2)]
            )
        else:
            features["known_loss_evidence"] = "Strong"
    return features


def set_occupant_counts(fake, plans):
    """A police report lists the occupants. Where no planner set the number, the car held the
    claimants plus 0 to 2 people who did not claim. So honest claimants never exceed occupants."""
    claimants_by_incident = {}
    for plan in plans:
        incident_key = plan["incident"]["key"]
        claimants_by_incident[incident_key] = (
            claimants_by_incident.get(incident_key, 0) + 1
        )
    for plan in plans:
        incident = plan["incident"]
        if incident["has_police_report"] and incident["occupants_listed"] is None:
            incident["occupants_listed"] = claimants_by_incident[
                incident["key"]
            ] + fake.random.randint(0, 2)


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.plan_signals_and_features      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    from faker import Faker

    from src.data_generation.claim_plan_blocks import make_world
    from src.data_generation.generate_tables import TABLE_NAMES
    from src.data_generation.plan_fraud_claims import plan_lone_fraud

    fake = Faker("en_US")
    fake.seed_instance(42)
    print(
        "1. weighted_choice (6 and 1 as weights):",
        [weighted_choice(fake, [("Strong", 6), ("Unclear", 1)]) for _ in range(8)],
    )

    world = make_world(fake, {table_name: [] for table_name in TABLE_NAMES})
    plan = plan_lone_fraud(fake, world, "build_up")[0]
    plan["signals"] = {"BI-2", "BI-3"}  # pretend these two rules were planted
    print("2. rule_applies BI-5 (no attorney):", rule_applies("BI-5", plan))
    features = choose_features(fake, plan)
    print(
        "3. choose_features: treatment_growth =",
        features["treatment_growth"],
        "| objective_support =",
        features["objective_support"],
        "| harmless example:",
        features["injury_crash_fit"],
    )
