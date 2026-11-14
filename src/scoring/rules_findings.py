"""The yes/no checks of the rules that read PDF findings.

BI-1..4 (injury), AS-1..6 (accident story), BF-5, BF-6 (billing), CT-5, CT-6 (coverage).
AS-6 reads one finding and one table fact. Not here yet: NL-4 (copied story).

The LLM rated the features earlier. Here plain code only asks: "does the one merged finding of this
feature have a firing rating?" (src/scoring/findings.py). The LLM never decides if a rule fires
(CLAUDE.md, rule 16). If the feature has no finding of Medium confidence or higher, the rule is
"not evaluated". The proof holds the quote, the document and the page (CLAUDE.md, rules 6 and 17).
"""

from src import config
from src.scoring.rule_results import fired_or_not, not_evaluated


def finding_proof(finding):
    return {
        "finding_id": finding["finding_id"],
        "value": finding["value"],
        "confidence": finding["confidence"],
        "document_id": finding["document_id"],
        "page_number": finding["page_number"],
        "quote": finding["quote"],
    }


def check_feature(facts, feature, firing_values):
    """Fired when the merged finding of the feature has one of the firing ratings."""
    finding = facts["findings"].get(feature)
    if finding is None:
        return not_evaluated(
            f"no {feature} finding with {config.MIN_CONFIDENCE} confidence or higher"
        )
    return fired_or_not(
        finding["value"] in firing_values, {"findings": [finding_proof(finding)]}
    )


def check_bi_1(facts):
    """The injury does not fit the crash."""
    return check_feature(facts, "injury_crash_fit", ["Inconsistent"])


def check_bi_2(facts):
    """The treatment grew far beyond what the injury needs."""
    return check_feature(facts, "treatment_growth", ["Disproportionate", "Extreme"])


def check_bi_3(facts):
    """Tests do not support the complaints."""
    return check_feature(
        facts, "objective_support", ["Predominantly subjective", "Contradicted"]
    )


def check_bi_4(facts):
    """An earlier condition of the same body area is a large part of the complaints."""
    return check_feature(facts, "pre_existing_condition", ["Material", "Predominant"])


def check_as_1(facts):
    """No independent source confirms the accident."""
    return check_feature(facts, "occurrence_support", ["Uncorroborated"])


def check_as_2(facts):
    """Sources contradict the accident story, or it looks staged."""
    return check_feature(
        facts, "occurrence_support", ["Contradicted", "Suspected staged"]
    )


def check_as_3(facts):
    """The vehicle damage does not fit the described impact."""
    return check_feature(facts, "damage_crash_fit", ["Inconsistent"])


def check_as_4(facts):
    """The claimant's story changed in an important way."""
    return check_feature(facts, "account_stability", ["Materially changed"])


def check_as_5(facts):
    """The claimant was added to the vehicle later, or was not in it."""
    return check_feature(facts, "occupant_presence", ["Added later", "Not present"])


def check_as_6(facts):
    """More different claimants filed for the incident than the police report lists as occupants.

    The occupant number is a finding (a number, not a rating). The claimant count is a table fact."""
    finding = facts["findings"].get("occupants_listed")
    if finding is None:
        return not_evaluated(
            f"no occupants_listed finding with {config.MIN_CONFIDENCE} confidence or higher"
        )
    if facts["incident_claimant_count"] is None:
        return not_evaluated("the claim has no incident")
    return fired_or_not(
        facts["incident_claimant_count"] > finding["value"],
        {
            "incident_id": facts["incident_id"],
            "claimants_in_incident": facts["incident_claimant_count"],
            "findings": [finding_proof(finding)],
        },
    )


def check_bf_5(facts):
    """The same service or part was billed twice (confirmed)."""
    return check_feature(facts, "duplicate_billing", ["Confirmed"])


def check_bf_6(facts):
    """The repair labor hours are excessive."""
    return check_feature(facts, "labor_hours_plausibility", ["Excessive"])


def check_ct_5(facts):
    """Damage from before the crash is documented, or the loss was known before the policy started.

    Two features feed this rule, so it cannot use check_feature. One feature is enough to evaluate it."""
    prior = facts["findings"].get("prior_damage_evidence")
    known = facts["findings"].get("known_loss_evidence")
    if prior is None and known is None:
        return not_evaluated(
            "no prior_damage_evidence or known_loss_evidence finding with "
            f"{config.MIN_CONFIDENCE} confidence or higher"
        )
    prior_fires = prior is not None and prior["value"] in ["Documented", "Material"]
    known_fires = known is not None and known["value"] == "Strong"
    proofs = [
        finding_proof(finding) for finding in [prior, known] if finding is not None
    ]
    return fired_or_not(prior_fires or known_fires, {"findings": proofs})


def check_ct_6(facts):
    """The driver is not on the policy."""
    return check_feature(facts, "driver_status", ["Unlisted", "Excluded"])


FINDING_RULE_CHECKS = {
    "BI-1": check_bi_1,
    "BI-2": check_bi_2,
    "BI-3": check_bi_3,
    "BI-4": check_bi_4,
    "AS-1": check_as_1,
    "AS-2": check_as_2,
    "AS-3": check_as_3,
    "AS-4": check_as_4,
    "AS-5": check_as_5,
    "AS-6": check_as_6,
    "BF-5": check_bf_5,
    "BF-6": check_bf_6,
    "CT-5": check_ct_5,
    "CT-6": check_ct_6,
}


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":

    def made_up_finding(feature, value):
        return {
            "finding_id": f"D-p1-{feature}",
            "feature": feature,
            "value": value,
            "confidence": "High",
            "document_id": "D",
            "page_number": 1,
            "quote": "a quote copied from the page",
        }

    sample_facts = {
        "incident_id": "I-1",
        "incident_claimant_count": 3,
        "findings": {
            "treatment_growth": made_up_finding("treatment_growth", "Extreme"),
            "injury_crash_fit": made_up_finding("injury_crash_fit", "Strong"),
            "known_loss_evidence": made_up_finding("known_loss_evidence", "Strong"),
        },
    }
    for rule_id, check in FINDING_RULE_CHECKS.items():
        print(rule_id, check(sample_facts)["status"])
