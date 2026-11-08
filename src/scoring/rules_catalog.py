"""The rule catalog: one record for each scoring rule (PLAN-v2.md, A7).

Rules are data (CLAUDE.md, rule 16). This file only DESCRIBES the rules.
The yes/no check of each rule is a plain function in src/scoring/rules.py (V7, V8).
Points are starting values. The names and numbers are our own.

`needs` lists the inputs of a rule. The prefix says where the input comes from:
  feature:<code>   a rated finding read from a PDF (src/documents/feature_catalog.py)
  table:<field>    a table value, stored as a graph property
  graph:<name>     a network query on the graph
  intake:<name>    the v1 conflict check of the Intake agent
A rule whose inputs are missing counts as "not fired" and is listed as "not evaluated".
"""

from dataclasses import dataclass

CATEGORY_NAMES = {
    "BI": "Bodily Injury and Treatment",
    "AS": "Accident Staging",
    "BF": "Billing and Expense",
    "CT": "Coverage Trigger",
    "NL": "Network Links",
}

SOURCE_NAMES = {"T": "tables", "N": "notes findings", "G": "graph query", "P": "PDF conflict check",
                "T+N": "tables and notes findings"}


# @dataclass writes __init__ for us: Rule(rule_id="BI-1", category="BI", ...) makes one record.
# frozen=True: a record cannot be changed after it is made, so nobody edits points by accident.
@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    name: str
    points: int
    source: str
    description: str
    enabled: bool
    needs: tuple


RULES = [
    # --- BI: Bodily Injury and Treatment ---
    Rule("BI-1", "BI", "Injury does not fit the crash", 15, "N",
         "injury_crash_fit is Inconsistent", True, ("feature:injury_crash_fit",)),
    Rule("BI-2", "BI", "Medical build-up", 12, "N",
         "treatment_growth is Disproportionate or Extreme", True, ("feature:treatment_growth",)),
    Rule("BI-3", "BI", "Mostly subjective findings", 8, "N",
         "objective_support is Predominantly subjective or Contradicted", True, ("feature:objective_support",)),
    Rule("BI-4", "BI", "Pre-existing condition contributes", 8, "N",
         "pre_existing_condition is Material or Predominant", True, ("feature:pre_existing_condition",)),
    Rule("BI-5", "BI", "Attorney before first treatment", 6, "T",
         "attorney_retained_date is before the first visit date", True,
         ("table:claims.attorney_retained_date", "table:treatments.visit_date")),
    Rule("BI-6", "BI", "Heavy early treatment", 8, "T",
         "more than 12 visits in the first 30 days after the loss date", True,
         ("table:claims.loss_date", "table:treatments.visit_date")),
    # --- AS: Accident Staging ---
    Rule("AS-1", "AS", "Accident not corroborated", 8, "N",
         "occurrence_support is Uncorroborated", True, ("feature:occurrence_support",)),
    Rule("AS-2", "AS", "Accident contradicted or suspected staged", 20, "N",
         "occurrence_support is Contradicted or Suspected staged", True, ("feature:occurrence_support",)),
    Rule("AS-3", "AS", "Damage does not fit the story", 12, "N",
         "damage_crash_fit is Inconsistent", True, ("feature:damage_crash_fit",)),
    Rule("AS-4", "AS", "Story changes between accounts", 12, "N",
         "account_stability is Materially changed", True, ("feature:account_stability",)),
    Rule("AS-5", "AS", "Occupant not present or added later", 18, "N",
         "occupant_presence is Added later or Not present", True, ("feature:occupant_presence",)),
    Rule("AS-6", "AS", "More claimants than occupants", 15, "T+N",
         "claimants in the incident are more than occupants_listed", True,
         ("table:claims.incident_id", "feature:occupants_listed")),
    Rule("AS-7", "AS", "Documents disagree on the loss date", 10, "P",
         "Intake finds a loss date conflict (v1 conflict check)", True, ("intake:loss_date_conflict",)),
    # --- BF: Billing and Expense ---
    Rule("BF-1", "BF", "Fast reserve rise", 8, "T",
         "reserve grows more than 50% within 30 days", True, ("table:reserve_events",)),
    Rule("BF-2", "BF", "Payments far above reserve", 8, "T",
         "paid is at least 1.5 times the reserve", True, ("table:payments", "table:reserve_events")),
    Rule("BF-3", "BF", "Many payments close together", 6, "T",
         "3 or more payments within 14 days", True, ("table:payments",)),
    Rule("BF-4", "BF", "Repair cost far above first estimate", 10, "T",
         "repair paid is at least 1.5 times repair_estimate_amount", True,
         ("table:payments", "table:claims.repair_estimate_amount")),
    Rule("BF-5", "BF", "Duplicate billing", 12, "N",
         "duplicate_billing is Confirmed", True, ("feature:duplicate_billing",)),
    Rule("BF-6", "BF", "Excess labor hours", 10, "N",
         "labor_hours_plausibility is Excessive", True, ("feature:labor_hours_plausibility",)),
    # --- CT: Coverage Trigger ---
    Rule("CT-1", "CT", "Loss soon after policy start", 10, "T",
         "loss_date minus customer_since is under 30 days", True,
         ("table:claims.loss_date", "table:policies.customer_since")),
    Rule("CT-2", "CT", "Loss soon after coverage increase", 10, "T",
         "loss_date minus last_coverage_increase_date is 0 to 30 days", True,
         ("table:claims.loss_date", "table:policies.last_coverage_increase_date")),
    Rule("CT-3", "CT", "Loss outside the policy dates", 20, "T",
         "loss_date is before effective_date, after expiration_date, or inside a lapse", True,
         ("table:claims.loss_date", "table:policies.effective_date", "table:policies.expiration_date")),
    Rule("CT-4", "CT", "Late reporting", 6, "T",
         "reported_date minus loss_date is over 30 days", True,
         ("table:claims.loss_date", "table:claims.reported_date")),
    Rule("CT-5", "CT", "Prior or known damage shown as new", 14, "N",
         "prior_damage_evidence is Documented or Material, or known_loss_evidence is Strong", True,
         ("feature:prior_damage_evidence", "feature:known_loss_evidence")),
    Rule("CT-6", "CT", "Driver not on the policy", 12, "N",
         "driver_status is Unlisted or Excluded", True, ("feature:driver_status",)),
    Rule("CT-7", "CT", "Suit filed near the deadline", 8, "T",
         "lawsuit filed_date is within 30 days before filing_deadline", True,
         ("table:lawsuits.filed_date", "table:lawsuits.filing_deadline")),
    # --- NL: Network Links (graph only; links inside one incident do not count) ---
    Rule("NL-1", "NL", "Shared phone or address", 8, "G",
         "strong link (a) phone or (b) address to a claim in a different incident", True,
         ("graph:strong_link_phone_or_address",)),
    Rule("NL-2", "NL", "Repeat claimant", 8, "G",
         "the claimant has 2 or more other claims in 36 months", True, ("graph:repeat_claimant",)),
    Rule("NL-3", "NL", "Same clinic and same attorney", 14, "G",
         "strong link (c) same clinic AND same attorney to 5 or more claims", True,
         ("graph:strong_link_clinic_and_attorney",)),
    Rule("NL-4", "NL", "Copied story", 14, "G",
         "story chunk similarity of 0.985 or more with a claim in a different incident", True,
         ("graph:copied_story",)),
    Rule("NL-5", "NL", "Same law firm and same expert", 12, "G",
         "strong link (d) same law firm AND same expert to 3 or more lawsuits within 12 months", True,
         ("graph:strong_link_firm_and_expert",)),
    Rule("NL-6", "NL", "Large linked cluster", 10, "G",
         "the claim sits in a group of 8 or more claims joined by strong links (up to 3 hops)", True,
         ("graph:strong_link_cluster",)),
]

RULES_BY_ID = {rule.rule_id: rule for rule in RULES}


def enabled_points_by_category():
    """{category: sum of the points of its enabled rules}. Example: {"BI": 57, ...}."""
    totals = {category: 0 for category in CATEGORY_NAMES}
    for rule in RULES:
        if rule.enabled:
            totals[rule.category] += rule.points
    return totals


def features_needed(rule):
    """The feature codes in a rule's needs. Example: BI-1 -> ["injury_crash_fit"]."""
    codes = []
    for need in rule.needs:
        if need.startswith("feature:"):
            codes.append(need.removeprefix("feature:"))
    return codes


def rules_table_lines():
    """The catalog as printable lines (show-rules)."""
    lines = [f"{'ID':<5} {'Pts':>3}  {'Src':<3}  {'On':<3} {'Name':<42} Logic", "-" * 120]
    for category, category_name in CATEGORY_NAMES.items():
        lines.append(f"{category} - {category_name}")
        for rule in RULES:
            if rule.category == category:
                lines.append(f"{rule.rule_id:<5} {rule.points:>3}  {rule.source:<3}  {'yes' if rule.enabled else 'no':<3} "
                             f"{rule.name:<42} {rule.description}")
    totals = enabled_points_by_category()
    lines.append("-" * 120)
    lines.append("Enabled points: " + ", ".join(f"{category} {points}" for category, points in totals.items())
                 + f". Rules: {len(RULES)}.")
    return lines
