"""The feature catalog: the facts the Intake agent reads from PDFs (PLAN-v2.md, A6).

A feature has allowed ratings, from least to most suspicious. A finding is one rating
of one feature for one claim, with a quote and a page (V6).

merge: how plain code picks ONE value when a claim has many findings of a feature.
  "worst"  = the most suspicious rating wins (a billing problem cannot be undone later)
  "latest" = the newest finding wins (later evidence can settle the fact)
value_type: "rating" (one of the allowed ratings) or "number" (occupants_listed).
document_types use the repo's document type names (data/pdfs/documents.csv).
"""

from dataclasses import dataclass

MERGE_METHODS = ["worst", "latest"]


@dataclass(frozen=True)
class Feature:
    code: str
    label: str
    ratings: tuple          # least suspicious first; empty for a number
    document_types: tuple
    merge: str
    used_by: tuple          # rule IDs
    value_type: str = "rating"


FEATURES = [
    Feature("injury_crash_fit", "Injury fits the crash",
            ("Strong", "Reasonable", "Unclear", "Inconsistent"),
            ("medical_records", "police_report", "adjuster_file"), "latest", ("BI-1",)),
    Feature("treatment_growth", "Treatment growth over time",
            ("Normal", "Elevated", "Disproportionate", "Extreme"),
            ("medical_records", "adjuster_file"), "worst", ("BI-2",)),
    Feature("objective_support", "Objective medical support",
            ("Strong", "Partial", "Predominantly subjective", "Contradicted"),
            ("medical_records",), "latest", ("BI-3",)),
    Feature("pre_existing_condition", "Pre-existing condition",
            ("None", "Minor", "Material", "Predominant"),
            ("medical_records", "adjuster_file"), "worst", ("BI-4",)),
    Feature("occurrence_support", "The accident happened as told",
            ("Confirmed", "Partially corroborated", "Uncorroborated", "Contradicted", "Suspected staged"),
            ("police_report", "adjuster_file"), "latest", ("AS-1", "AS-2")),
    Feature("damage_crash_fit", "Damage fits the crash",
            ("Strong", "Reasonable", "Unclear", "Inconsistent"),
            ("repair_estimate", "police_report", "adjuster_file"), "latest", ("AS-3",)),
    Feature("account_stability", "The story stays the same",
            ("Stable", "Clarified", "Materially changed"),
            ("fnol", "adjuster_file"), "worst", ("AS-4",)),
    Feature("occupant_presence", "The claimant was in the vehicle",
            ("Verified", "Unclear", "Added later", "Not present"),
            ("police_report", "adjuster_file"), "latest", ("AS-5",)),
    Feature("occupants_listed", "Number of occupants on the police report", (),
            ("police_report",), "latest", ("AS-6",), value_type="number"),
    Feature("duplicate_billing", "Duplicate billing",
            ("None", "Possible", "Confirmed"),
            ("medical_records", "repair_estimate"), "worst", ("BF-5",)),
    Feature("labor_hours_plausibility", "Repair labor hours are plausible",
            ("Plausible", "Elevated", "Excessive"),
            ("repair_estimate",), "worst", ("BF-6",)),
    Feature("prior_damage_evidence", "Evidence of prior damage",
            ("None", "Possible", "Documented", "Material"),
            ("repair_estimate", "police_report", "adjuster_file"), "worst", ("CT-5",)),
    Feature("known_loss_evidence", "Evidence the loss was known before the policy",
            ("Weak", "Moderate", "Strong"),
            ("adjuster_file",), "worst", ("CT-5",)),
    Feature("driver_status", "The driver is on the policy",
            ("Listed", "Household", "Unlisted", "Excluded"),
            ("police_report", "fnol", "adjuster_file"), "latest", ("CT-6",)),
]

FEATURES_BY_CODE = {feature.code: feature for feature in FEATURES}


def features_table_lines():
    """The catalog as printable lines (show-features)."""
    lines = [f"{'Feature':<25} {'Merge':<6} {'Used by':<10} {'Found in':<45} Allowed ratings (least to most suspicious)",
             "-" * 150]
    for feature in FEATURES:
        ratings = " < ".join(feature.ratings) if feature.value_type == "rating" else "a number"
        lines.append(f"{feature.code:<25} {feature.merge:<6} {', '.join(feature.used_by):<10} "
                     f"{', '.join(feature.document_types):<45} {ratings}")
    lines.append("-" * 150)
    lines.append(f"Features: {len(FEATURES)}.")
    return lines
