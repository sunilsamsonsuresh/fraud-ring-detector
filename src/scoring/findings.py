"""Findings: read the PDF findings of one claim and keep ONE usable finding per feature.

A claim can have several findings for one feature, from several documents. Example: treatment_growth
is rated "Normal" in one note and "Disproportionate" in a later one. A rule needs one value.
Plain code picks it, in two steps:
1. Drop findings below config.MIN_CONFIDENCE. They fire no rule. We return them too, as "weak findings".
2. For each feature, keep one finding by its merge method:
   "worst"  = the most suspicious rating wins (a billing problem cannot be undone later).
   "latest" = the newest finding wins (later evidence can settle the fact).

No LLM is called here. The LLM wrote the findings earlier; this file only reads and sorts them.
"""

from src import config
from src.graph import queries
from src.tools.claim_tools import rows_from

# Feature -> merge method: which finding wins when several documents rate the same feature.
FEATURE_MERGE_METHODS = {
    "injury_crash_fit": "latest",
    "treatment_growth": "worst",
    "objective_support": "latest",
    "pre_existing_condition": "worst",
    "occurrence_support": "latest",
    "damage_crash_fit": "latest",
    "account_stability": "worst",
    "occupant_presence": "latest",
    "occupants_listed": "latest",
    "duplicate_billing": "worst",
    "labor_hours_plausibility": "worst",
    "prior_damage_evidence": "worst",
    "known_loss_evidence": "worst",
    "driver_status": "latest",
}


def read_findings(driver, claim_id):
    """All findings of the claim, as stored. note_date becomes a Python date (or None)."""
    findings = []
    for row in rows_from(driver, queries.CLAIM_FINDINGS, claim_id):
        if row["note_date"] is not None:
            row["note_date"] = row["note_date"].to_native()
        findings.append(row)
    return findings


def is_strong_enough(finding):
    """True when the confidence is config.MIN_CONFIDENCE or higher. An unknown word counts as too weak."""
    levels = config.CONFIDENCE_LEVELS
    if finding["confidence"] not in levels:
        return False
    return levels.index(finding["confidence"]) >= levels.index(config.MIN_CONFIDENCE)


def newest_first_key(finding):
    """Sort key for "latest": note date, then document ID, then page. No date counts as oldest."""
    note_date = finding["note_date"]
    date_text = note_date.isoformat() if note_date is not None else ""
    return (date_text, finding["document_id"], finding["page_number"])


def merge_findings(findings):
    """{feature: the one finding that wins}. Only features with at least one finding appear."""
    merged = {}
    for finding in findings:
        feature = finding["feature"]
        method = FEATURE_MERGE_METHODS.get(feature)
        if method is None:
            continue  # a feature we do not know: no rule reads it
        current = merged.get(feature)
        if (
            current is None
            or method == "worst"
            and finding["severity_rank"] > current["severity_rank"]
            or method == "latest"
            and newest_first_key(finding) > newest_first_key(current)
        ):
            merged[feature] = finding
    return merged


def usable_and_weak_findings(driver, claim_id):
    """(merged findings of Medium or higher confidence, list of weak findings)."""
    strong, weak = [], []
    for finding in read_findings(driver, claim_id):
        if is_strong_enough(finding):
            strong.append(finding)
        else:
            weak.append(finding)
    return merge_findings(strong), weak


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with the "Debug the open file" configuration, or:  .venv/bin/python -m src.scoring.findings
# Neo4j must be running.
if __name__ == "__main__":
    from src.graph.connection import open_neo4j_driver

    driver = open_neo4j_driver()
    try:
        merged, weak = usable_and_weak_findings(driver, "C-1088")
        print(
            "Raw findings:", len(read_findings(driver, "C-1088")), "| weak:", len(weak)
        )
        for feature, finding in merged.items():
            print(
                f"{feature:<26} {finding['value']:<26} {finding['confidence']:<7} "
                f"{finding['document_id']} page {finding['page_number']}"
            )
    finally:
        driver.close()
