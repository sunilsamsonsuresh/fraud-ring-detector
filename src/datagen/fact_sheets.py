"""Fact sheets: the planted feature values of a claim, as plain sentences for the LLM (PLAN-v2.md A4, V4).

The LLM writes the prose of a document from these facts. The sentences never use the
rating labels ("Predominantly subjective", "Materially changed" ...), so the documents carry
the facts, not the answer key. V6 must read the rating back from the prose.

Each document type gets only the features that PLAN-v2.md A6 lists for it
(src/documents/feature_catalog.py, document_types).
"""

from src.documents.feature_catalog import FEATURES

# (feature, rating) -> a plain fact. No rating label appears in these sentences.
FACT_PHRASES = {
    ("injury_crash_fit", "Strong"): "The reported injury matches the kind and force of the crash well.",
    ("injury_crash_fit", "Reasonable"): "The reported injury is plausible for a crash like this one.",
    ("injury_crash_fit", "Unclear"): "It is not yet clear whether the injury came from this crash.",
    ("injury_crash_fit", "Inconsistent"): "The injury does not fit the crash: the impact was very light, "
                                          "yet the claimed injury is severe.",
    ("treatment_growth", "Normal"): "Treatment followed a usual course and tapered off as the patient improved.",
    ("treatment_growth", "Elevated"): "Treatment ran somewhat longer than usual for this injury.",
    ("treatment_growth", "Disproportionate"): "Treatment kept growing well beyond what this injury usually "
                                              "needs, with more visits and new services added month after month.",
    ("treatment_growth", "Extreme"): "Treatment grew to many times the usual amount for this injury, with "
                                     "near-daily visits and new body areas added weeks after the crash.",
    ("objective_support", "Strong"): "Imaging and exam findings clearly confirm the injury.",
    ("objective_support", "Partial"): "Some exam findings support the injury; other tests are normal.",
    ("objective_support", "Predominantly subjective"): "Nearly all findings rest on the patient's own pain "
                                                       "reports; imaging and exam tests are normal.",
    ("objective_support", "Contradicted"): "Objective tests go against the complaints: imaging is normal and "
                                           "the patient moved freely when observed outside the exam room.",
    ("pre_existing_condition", "None"): "No earlier injury to the same body area is known.",
    ("pre_existing_condition", "Minor"): "Years ago the patient had a small strain in the same area that healed fully.",
    ("pre_existing_condition", "Material"): "The patient was treated for the same body area within the last two "
                                            "years, and that condition adds to the current complaints.",
    ("pre_existing_condition", "Predominant"): "Records show long-standing treatment for the same condition before "
                                               "the crash; most of the current complaints come from it.",
    ("occurrence_support", "Confirmed"): "Witnesses, photos and the other driver all confirm the accident "
                                         "happened as described.",
    ("occurrence_support", "Partially corroborated"): "Photos confirm some details, but there are no "
                                                      "independent witnesses.",
    ("occurrence_support", "Uncorroborated"): "Nothing independent confirms the accident: no witnesses, no "
                                              "photos and no other report.",
    ("occurrence_support", "Contradicted"): "Evidence goes against the account: a nearby camera shows no "
                                            "collision at that place and time.",
    ("occurrence_support", "Suspected staged"): "Signs point to a set-up crash: the front car braked hard for no "
                                                "reason and the people in both cars knew each other.",
    ("damage_crash_fit", "Strong"): "The vehicle damage matches the described impact.",
    ("damage_crash_fit", "Reasonable"): "The damage is mostly in line with the described impact.",
    ("damage_crash_fit", "Unclear"): "It is not clear whether all of the damage came from this impact.",
    ("damage_crash_fit", "Inconsistent"): "The damage does not match the story: the dents are on another side "
                                          "and at another height than the described impact.",
    ("account_stability", "Stable"): "The claimant told the same account in every conversation.",
    ("account_stability", "Clarified"): "The claimant later added small details, but the account stayed the same.",
    ("account_stability", "Materially changed"): "The claimant's account changed in important ways between "
                                                 "conversations: the direction of the impact and the number of "
                                                 "people in the car are now different.",
    ("occupant_presence", "Verified"): "The police and witnesses confirm the claimant was in the vehicle.",
    ("occupant_presence", "Unclear"): "It is not fully clear where in the vehicle the claimant was sitting.",
    ("occupant_presence", "Added later"): "Nobody gave the claimant's name at the scene; the claimant joined "
                                          "the claim days later.",
    ("occupant_presence", "Not present"): "Witnesses and the officer say the claimant was not in the vehicle "
                                          "when the crash happened.",
    ("duplicate_billing", "None"): "The bills show no repeated charges.",
    ("duplicate_billing", "Possible"): "Two similar charges on the same day are being checked.",
    ("duplicate_billing", "Confirmed"): "The same service was billed twice for the same date, and the provider "
                                        "admitted the second charge was a repeat.",
    ("labor_hours_plausibility", "Plausible"): "The repair labor hours fit the damage.",
    ("labor_hours_plausibility", "Elevated"): "The repair labor hours are a little high for this damage.",
    ("labor_hours_plausibility", "Excessive"): "The repair labor hours are far more than the damage needs, "
                                               "about three times a normal estimate.",
    ("prior_damage_evidence", "None"): "No earlier damage to the vehicle is known.",
    ("prior_damage_evidence", "Possible"): "A few old scratches may be older than this crash.",
    ("prior_damage_evidence", "Documented"): "A dated inspection photo shows the same dent before this crash.",
    ("prior_damage_evidence", "Material"): "Records show the same major damage from an earlier, unreported "
                                           "accident; it is now claimed as new.",
    ("known_loss_evidence", "Weak"): "Nothing suggests the damage happened before the coverage started.",
    ("known_loss_evidence", "Moderate"): "A neighbor thinks the car was damaged some weeks before the claimed date.",
    ("known_loss_evidence", "Strong"): "A dated repair quote from before the policy start shows this same "
                                       "damage already existed.",
    ("driver_status", "Listed"): "The driver is named on the policy.",
    ("driver_status", "Household"): "The driver lives with the policyholder and is covered as a household member.",
    ("driver_status", "Unlisted"): "The driver is not named on the policy and does not live with the policyholder.",
    ("driver_status", "Excluded"): "The driver was named on the policy as a person who may NOT drive the car.",
}

# Long rating labels that must never appear in a document (V4 done test). Common words
# ("Strong", "Normal") and everyday phrases ("not present", "added later") are allowed.
FORBIDDEN_LABELS = ["Predominantly subjective", "Partially corroborated", "Suspected staged",
                    "Materially changed", "Disproportionate", "Uncorroborated"]
# If the LLM still writes a label after one stricter retry, plain code swaps in plain words.
LABEL_REPLACEMENTS = {"predominantly subjective": "mostly based on the patient's own reports",
                      "partially corroborated": "confirmed in part", "suspected staged": "possibly set up",
                      "materially changed": "changed in important ways", "disproportionate": "out of proportion",
                      "uncorroborated": "not confirmed by anyone else"}


def facts_for_document(document_type, planted_features):
    """The fact sentences for one document type, as a bulleted string (or "" when none apply)."""
    lines = []
    for feature in FEATURES:
        if document_type not in feature.document_types or feature.value_type != "rating":
            continue
        value = planted_features.get(feature.code)
        if value is not None:
            lines.append("- " + FACT_PHRASES[(feature.code, value)])
    return "\n".join(lines)


def find_forbidden_labels(text):
    """The rating labels that appear in the text, ignoring case."""
    lower_text = text.lower()
    return [label for label in FORBIDDEN_LABELS if label.lower() in lower_text]


def replace_forbidden_labels(text):
    """Swap each forbidden label for plain words (any case). The last safety net."""
    for label, plain_words in LABEL_REPLACEMENTS.items():
        position = text.lower().find(label)
        while position != -1:
            text = text[:position] + plain_words + text[position + len(label):]
            position = text.lower().find(label, position + len(plain_words))
    return text
