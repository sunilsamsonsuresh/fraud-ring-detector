"""Plain metrics for one layer of scores (PLAN-v2.md A10, V15). No LLM, no Neo4j.

Input: a list of rows, one per claim:
  {"claim_id", "is_fraud", "fraud_type", "lookalike_group", "total_score", "band"}
"Flagged at High" means the band is High or Very High. "Flagged at Medium" means Medium or above.
Precision = flagged fraud claims / all flagged claims.   Recall = flagged fraud claims / all fraud claims.
"""

BANDS_AT_OR_ABOVE = {
    "Medium": ["Medium", "High", "Very High"],
    "High": ["High", "Very High"],
}
TOP_COUNT = 25


def share(part, whole):
    """A share from 0 to 1, or None when the whole is 0 (then the share is unknown, not 0)."""
    return part / whole if whole else None


def flagged(row, level):
    return row["band"] in BANDS_AT_OR_ABOVE[level]


def precision_and_recall(rows, level):
    flagged_rows = [row for row in rows if flagged(row, level)]
    flagged_fraud = sum(1 for row in flagged_rows if row["is_fraud"])
    all_fraud = sum(1 for row in rows if row["is_fraud"])
    return {"flagged": len(flagged_rows), "flagged_fraud": flagged_fraud, "all_fraud": all_fraud,
            "precision": share(flagged_fraud, len(flagged_rows)), "recall": share(flagged_fraud, all_fraud)}


def precision_in_top(rows, count=TOP_COUNT):
    """The share of fraud claims among the `count` highest scores (ties broken by claim ID)."""
    ordered = sorted(rows, key=lambda row: (-row["total_score"], row["claim_id"]))[:count]
    return share(sum(1 for row in ordered if row["is_fraud"]), len(ordered))


def recall_by_fraud_type(rows, level):
    """{fraud type: (flagged, all)} for the fraud claims."""
    result = {}
    for row in rows:
        if row["is_fraud"]:
            flagged_count, all_count = result.get(row["fraud_type"], (0, 0))
            result[row["fraud_type"]] = (flagged_count + flagged(row, level), all_count + 1)
    return dict(sorted(result.items()))


def lookalike_false_alarms(rows, level):
    """{lookalike group: (flagged, all)} for the honest lookalike claims."""
    result = {}
    for row in rows:
        if row["lookalike_group"] and not row["is_fraud"]:
            flagged_count, all_count = result.get(row["lookalike_group"], (0, 0))
            result[row["lookalike_group"]] = (flagged_count + flagged(row, level), all_count + 1)
    return dict(sorted(result.items()))


def band_table(rows):
    """{band: {"fraud": n, "honest": n}}, Low to Very High."""
    table = {band: {"fraud": 0, "honest": 0} for band in ["Low", "Medium", "High", "Very High"]}
    for row in rows:
        table[row["band"]]["fraud" if row["is_fraud"] else "honest"] += 1
    return table


def layer_metrics(rows):
    """Every A10 measure for one layer."""
    return {
        "band_table": band_table(rows),
        "at_medium": precision_and_recall(rows, "Medium"),
        "at_high": precision_and_recall(rows, "High"),
        "precision_top_25": precision_in_top(rows),
        "recall_by_fraud_type_at_medium": recall_by_fraud_type(rows, "Medium"),
        "recall_by_fraud_type_at_high": recall_by_fraud_type(rows, "High"),
        "lookalike_false_alarms_at_medium": lookalike_false_alarms(rows, "Medium"),
        "lookalike_false_alarms_at_high": lookalike_false_alarms(rows, "High"),
    }
