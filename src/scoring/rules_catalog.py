"""The rule catalog: one record for each scoring rule.

Rules are data (CLAUDE.md, rule 16). This file only DESCRIBES the rules.
The yes/no check of each rule is a plain function in another file.
The LLM never decides points and never decides if a rule fires.

The rules are in 5 categories. A rule with more points is a stronger sign of a problem.
The names and the numbers are the same as in the old system, so the scores stay comparable.
"""

from dataclasses import dataclass

CATEGORY_NAMES = {
    "BI": "Bodily Injury and Treatment",
    "AS": "Accident Staging",
    "BF": "Billing and Expense",
    "CT": "Coverage Trigger",
    "NL": "Network Links",
}


# @dataclass writes __init__ for us: Rule("BI-1", "BI", ...) makes one record with named fields.
# frozen=True: a record cannot be changed after it is made, so nobody edits points by accident.
@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    name: str
    points: int
    description: str  # when the rule fires, in plain words


RULES = [
    # --- BI: Bodily Injury and Treatment ---
    Rule(
        "BI-1",
        "BI",
        "Injury does not fit the crash",
        15,
        "injury_crash_fit is Inconsistent",
    ),
    Rule(
        "BI-2",
        "BI",
        "Medical build-up",
        12,
        "treatment_growth is Disproportionate or Extreme",
    ),
    Rule(
        "BI-3",
        "BI",
        "Mostly subjective findings",
        8,
        "objective_support is Predominantly subjective or Contradicted",
    ),
    Rule(
        "BI-4",
        "BI",
        "Pre-existing condition contributes",
        8,
        "pre_existing_condition is Material or Predominant",
    ),
    Rule(
        "BI-5",
        "BI",
        "Attorney before first treatment",
        6,
        "attorney_retained_date is before the first visit date",
    ),
    Rule(
        "BI-6",
        "BI",
        "Heavy early treatment",
        8,
        "more than 12 visits in the first 30 days after the loss date",
    ),
    # --- AS: Accident Staging ---
    Rule(
        "AS-1",
        "AS",
        "Accident not corroborated",
        8,
        "occurrence_support is Uncorroborated",
    ),
    Rule(
        "AS-2",
        "AS",
        "Accident contradicted or suspected staged",
        20,
        "occurrence_support is Contradicted or Suspected staged",
    ),
    Rule(
        "AS-3",
        "AS",
        "Damage does not fit the story",
        12,
        "damage_crash_fit is Inconsistent",
    ),
    Rule(
        "AS-4",
        "AS",
        "Story changes between accounts",
        12,
        "account_stability is Materially changed",
    ),
    Rule(
        "AS-5",
        "AS",
        "Occupant not present or added later",
        18,
        "occupant_presence is Added later or Not present",
    ),
    Rule(
        "AS-6",
        "AS",
        "More claimants than occupants",
        15,
        "claimants in the incident are more than occupants_listed",
    ),
    Rule(
        "AS-7",
        "AS",
        "Documents disagree on the loss date",
        10,
        "the documents of the claim give different loss dates",
    ),
    # --- BF: Billing and Expense ---
    Rule(
        "BF-1",
        "BF",
        "Fast reserve rise",
        8,
        "reserve grows more than 50% within 30 days",
    ),
    Rule(
        "BF-2",
        "BF",
        "Payments far above reserve",
        8,
        "paid is at least 1.5 times the reserve",
    ),
    Rule(
        "BF-3",
        "BF",
        "Many payments close together",
        6,
        "3 or more payments within 14 days",
    ),
    Rule(
        "BF-4",
        "BF",
        "Repair cost far above first estimate",
        10,
        "repair paid is at least 1.5 times repair_estimate_amount",
    ),
    Rule("BF-5", "BF", "Duplicate billing", 12, "duplicate_billing is Confirmed"),
    Rule(
        "BF-6", "BF", "Excess labor hours", 10, "labor_hours_plausibility is Excessive"
    ),
    # --- CT: Coverage Trigger ---
    Rule(
        "CT-1",
        "CT",
        "Loss soon after policy start",
        10,
        "loss_date minus customer_since is under 30 days",
    ),
    Rule(
        "CT-2",
        "CT",
        "Loss soon after coverage increase",
        10,
        "loss_date minus last_coverage_increase_date is 0 to 30 days",
    ),
    Rule(
        "CT-3",
        "CT",
        "Loss outside the policy dates",
        20,
        "loss_date is before effective_date, after expiration_date, or inside a lapse",
    ),
    Rule(
        "CT-4",
        "CT",
        "Late reporting",
        6,
        "reported_date minus loss_date is over 30 days",
    ),
    Rule(
        "CT-5",
        "CT",
        "Prior or known damage shown as new",
        14,
        "prior_damage_evidence is Documented or Material, or known_loss_evidence is Strong",
    ),
    Rule(
        "CT-6",
        "CT",
        "Driver not on the policy",
        12,
        "driver_status is Unlisted or Excluded",
    ),
    Rule(
        "CT-7",
        "CT",
        "Suit filed near the deadline",
        8,
        "lawsuit filed_date is within 30 days before the filing deadline (limitation_deadline)",
    ),
    # --- NL: Network Links (links inside one incident do not count) ---
    Rule(
        "NL-1",
        "NL",
        "Shared phone or address",
        8,
        "strong link (a) phone or (b) address to a claim in a different incident",
    ),
    Rule(
        "NL-2",
        "NL",
        "Repeat claimant",
        8,
        "the claimant has 2 or more other claims in 36 months",
    ),
    Rule(
        "NL-3",
        "NL",
        "Same clinic and same attorney",
        14,
        "strong link (c) same clinic AND same attorney to 5 or more claims",
    ),
    Rule(
        "NL-4",
        "NL",
        "Copied story",
        14,
        "story chunk similarity of 0.985 or more with a claim in a different incident",
    ),
    Rule(
        "NL-5",
        "NL",
        "Same law firm and same expert",
        12,
        "strong link (d) same law firm AND same expert to 3 or more lawsuits within 12 months",
    ),
    Rule(
        "NL-6",
        "NL",
        "Large linked cluster",
        10,
        "the claim sits in a group of 8 or more claims joined by strong links (up to 3 hops)",
    ),
]

RULES_BY_ID = {rule.rule_id: rule for rule in RULES}


def points_by_category():
    """{category: sum of the points of its rules}. A category score divides by this number."""
    totals = {category: 0 for category in CATEGORY_NAMES}
    for rule in RULES:
        totals[rule.category] += rule.points
    return totals
