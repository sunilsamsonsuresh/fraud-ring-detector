"""portfolio_overview: fixed views over all claims (PLAN-v2.md A9, V14). Plain code only.

Every view reads the latest ScoreSnapshot of each claim (made by score-all) with a fixed query.
- top_claims:       the highest total scores
- rules_fired_most: the rules that fire on the most claims
- claims_by_driver: the High and Very High claims, grouped by the category that adds the most points
- rising_claims:    claims whose score is rising (only claims with a score history have several snapshots)
"""

from src import config
from src.graph import queries
from src.graph.network import rows_of
from src.scoring.history import trend_of
from src.scoring.rules_catalog import CATEGORY_NAMES, RULES_BY_ID

SCORE_KEY_OF_CATEGORY = {"BI": "bi_score", "AS": "as_score", "BF": "bf_score", "CT": "ct_score", "NL": "nl_score"}
HIGH_BANDS = ["High", "Very High"]


def latest_snapshots(driver):
    records, _, _ = driver.execute_query(queries.LATEST_SNAPSHOTS)
    return rows_of(records)


def top_claims(rows, limit):
    ordered = sorted(rows, key=lambda row: (-row["total_score"], row["claim_id"]))
    facts = []
    for row in ordered[:limit]:
        facts.append({"claim_id": row["claim_id"], "total_score": row["total_score"], "band": row["band"],
                      "fired_rules": row["fired_rule_ids"], "band_after_challenger": row["investigated_band"]})
    return facts


def rules_fired_most(driver, scored_claim_count, limit):
    records, _, _ = driver.execute_query(queries.RULE_FIRE_COUNTS)
    ordered = sorted(rows_of(records), key=lambda row: (-row["claim_count"], row["rule_id"]))
    facts = []
    for row in ordered[:limit]:
        facts.append({"rule_id": row["rule_id"], "name": RULES_BY_ID[row["rule_id"]].name,
                      "claim_count": row["claim_count"],
                      "share_of_claims": f"{row['claim_count'] / max(scored_claim_count, 1):.0%}"})
    return facts


def driver_category(row):
    """The category that adds the most to the total: weight x category score."""
    best_category, best_points = None, -1.0
    for category in CATEGORY_NAMES:
        points = config.CATEGORY_WEIGHTS[category] * (row[SCORE_KEY_OF_CATEGORY[category]] or 0)
        if points > best_points:
            best_category, best_points = category, points
    return best_category


def claims_by_driver(rows):
    groups = {}
    for row in rows:
        if row["band"] in HIGH_BANDS:
            category = driver_category(row)
            groups.setdefault(category, []).append(row["claim_id"])
    facts = []
    for category in sorted(groups, key=lambda name: (-len(groups[name]), name)):
        facts.append({"category": category, "category_name": CATEGORY_NAMES[category],
                      "claim_count": len(groups[category]), "claim_ids": sorted(groups[category])})
    return facts


def rising_claims(driver, limit):
    """Return (rising claims, number of claims with more than one snapshot)."""
    records, _, _ = driver.execute_query(queries.ALL_SNAPSHOT_SCORES)
    history_by_claim = {}
    for row in rows_of(records):
        history_by_claim.setdefault(row["claim_id"], []).append(
            {"as_of_date": row["as_of_date"], "result": {"total_score": row["total_score"]}})
    with_history = {claim_id: history for claim_id, history in history_by_claim.items() if len(history) > 1}
    facts = []
    for claim_id in sorted(with_history):
        history = with_history[claim_id]
        if trend_of(history) == "rising":
            facts.append({"claim_id": claim_id, "first_score": history[0]["result"]["total_score"],
                          "latest_score": history[-1]["result"]["total_score"]})
    return facts[:limit], len(with_history)


def portfolio_overview(driver, view, limit):
    rows = latest_snapshots(driver)
    if not rows:
        return {"message": "No claim has a saved score yet. Run: python main.py score-all"}
    source = f"latest ScoreSnapshot of {len(rows)} claims (score-all)"
    notes = []
    if view == "top_claims":
        facts = top_claims(rows, limit)
        notes.append("band = the rule score before the Challenger; band_after_challenger is set only for "
                     "claims run with investigate.")
    elif view == "rules_fired_most":
        facts = rules_fired_most(driver, len(rows), limit)
    elif view == "claims_by_driver":
        facts = claims_by_driver(rows)
    else:
        facts, history_count = rising_claims(driver, limit)
        notes.append(f"Only {history_count} claims have a score history (python main.py score-history <claim>). "
                     "The trend of the other claims is unknown.")
    return {"view": view, "facts": facts, "notes": notes, "sources": [source]}
