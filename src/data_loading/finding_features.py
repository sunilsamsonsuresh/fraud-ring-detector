"""The list of features that the LLM rates on PDF pages.

A feature is a fixed question about a claim. Example: "Did the treatment grow beyond what the injury needs?"
A rating is one answer from a fixed list. The list goes from the least suspicious to the most suspicious.
Example for treatment_growth: Normal, Elevated, Disproportionate, Extreme.

A finding (extract_findings_from_pages.py) is one rating of one feature, with a quote and a page.
The scoring rules (src/scoring/rules_findings.py) read these findings. How the rules use each feature, and
how many findings of one feature are merged, is in src/scoring/findings.py. Here we keep only what the
reading of the PDFs needs.

@dataclass writes the __init__ function for us: Feature("a", "b", ...) makes one record with named fields.
frozen=True means that a record cannot be changed after it is made.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    code: str
    question: str  # shown to the LLM
    ratings: tuple  # the allowed ratings, least suspicious first. Empty for a number.
    document_types: tuple  # the LLM reads this feature only on these types of document
    value_type: str = "rating"  # "rating", or "number" (occupants_listed)


FEATURES = [
    Feature(
        "injury_crash_fit",
        "Does the claimed injury fit the type and force of the crash?",
        ("Strong", "Reasonable", "Unclear", "Inconsistent"),
        ("medical_records", "police_report", "adjuster_file"),
    ),
    Feature(
        "treatment_growth",
        "Did the treatment grow beyond what this injury needs?",
        ("Normal", "Elevated", "Disproportionate", "Extreme"),
        ("medical_records", "adjuster_file"),
    ),
    Feature(
        "objective_support",
        "Do objective tests (imaging, exam findings) support the complaints?",
        ("Strong", "Partial", "Predominantly subjective", "Contradicted"),
        ("medical_records",),
    ),
    Feature(
        "pre_existing_condition",
        "Did an earlier condition of the same body area add to the complaints?",
        ("None", "Minor", "Material", "Predominant"),
        ("medical_records", "adjuster_file"),
    ),
    Feature(
        "occurrence_support",
        "Do independent sources (witnesses, photos, cameras, the other driver) confirm "
        "that the accident happened as described?",
        (
            "Confirmed",
            "Partially corroborated",
            "Uncorroborated",
            "Contradicted",
            "Suspected staged",
        ),
        ("police_report", "adjuster_file"),
    ),
    Feature(
        "damage_crash_fit",
        "Does the vehicle damage fit the described impact?",
        ("Strong", "Reasonable", "Unclear", "Inconsistent"),
        ("repair_estimate", "police_report", "adjuster_file"),
    ),
    Feature(
        "account_stability",
        "Did the claimant's account of the accident stay the same over time?",
        ("Stable", "Clarified", "Materially changed"),
        ("fnol", "adjuster_file"),
    ),
    Feature(
        "occupant_presence",
        "Was the claimant really in the vehicle at the time of the crash?",
        ("Verified", "Unclear", "Added later", "Not present"),
        ("police_report", "adjuster_file"),
    ),
    Feature(
        "occupants_listed",
        "How many people does the police report list in the insured vehicle (Vehicle 1)? "
        "The rating is a whole number.",
        (),
        ("police_report",),
        value_type="number",
    ),
    Feature(
        "duplicate_billing",
        "Was the same service, visit or part billed twice?",
        ("None", "Possible", "Confirmed"),
        ("medical_records", "repair_estimate"),
    ),
    Feature(
        "labor_hours_plausibility",
        "Are the repair labor hours plausible for the damage?",
        ("Plausible", "Elevated", "Excessive"),
        ("repair_estimate",),
    ),
    Feature(
        "prior_damage_evidence",
        "Is there evidence of vehicle damage from before this crash?",
        ("None", "Possible", "Documented", "Material"),
        ("repair_estimate", "police_report", "adjuster_file"),
    ),
    Feature(
        "known_loss_evidence",
        "Is there evidence the damage existed or was known before the coverage started?",
        ("Weak", "Moderate", "Strong"),
        ("adjuster_file",),
    ),
    Feature(
        "driver_status",
        "Is the driver of the insured vehicle on the policy?",
        ("Listed", "Household", "Unlisted", "Excluded"),
        ("police_report", "fnol", "adjuster_file"),
    ),
]

FEATURES_BY_CODE = {feature.code: feature for feature in FEATURES}


def features_for(document_type):
    """The features that the LLM reads on this type of document."""
    return [feature for feature in FEATURES if document_type in feature.document_types]


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    print(len(FEATURES), "features.")
    print(
        "Read on an adjuster file:",
        [feature.code for feature in features_for("adjuster_file")],
    )
    print(
        "Read on a complaint:     ",
        [feature.code for feature in features_for("complaint")],
    )
    print("Ratings of treatment_growth:", FEATURES_BY_CODE["treatment_growth"].ratings)
