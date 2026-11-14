"""Pipeline step 4: score every claim with the fixed rules and save one ScoreSnapshot for each. No LLM is called.

The chat reads these saved scores for questions about MANY claims ("the highest scores", "how many High claims").
Step 5 (the communities) also reads them, so this step must run first.
Working out 500 scores at chat time would take too long, so the pipeline does it once here.

A snapshot is the score of one claim on one date (as_of_date). Scoring again on the same date replaces the
snapshot of that date; another date adds a new one. The newest snapshot is the current score.
The score is repeatable: the same data gives the same score (CLAUDE.md, section 7).

Run it:  .venv/bin/python -m src.data_loading.save_scores_into_graph
"""

import datetime
import json

from src.graph import queries
from src.scoring.engine import score_facts
from src.scoring.facts import read_claim_facts

# The query that WRITES. It lives here, with the pipeline step, and not in src/graph/queries.py (reads only).
# MERGE on snapshot_id ("C-1088-2026-11-14"): one snapshot for each claim and date.
SAVE_SCORE_SNAPSHOT = """
MATCH (claim:Claim {claim_id: $claim_id})
MERGE (snapshot:ScoreSnapshot {snapshot_id: $snapshot_id})
SET snapshot.claim_id = $claim_id, snapshot.as_of_date = date($as_of_date),
    snapshot.total_score = $total_score, snapshot.band = $band,
    snapshot.bi_score = $bi_score, snapshot.as_score = $as_score, snapshot.bf_score = $bf_score,
    snapshot.ct_score = $ct_score, snapshot.nl_score = $nl_score, snapshot.coverage_pct = $coverage_pct,
    snapshot.fired_rule_ids = $fired_rule_ids, snapshot.fired_rules_json = $fired_rules_json
MERGE (claim)-[:HAS_SCORE]->(snapshot)
"""


def save_snapshot(driver, result, as_of_date):
    """Save the score result of one claim (from score_facts) as the snapshot of as_of_date."""
    scores = result["category_scores"]
    fired_rule_ids = []
    for rule in result["fired_rules"]:
        fired_rule_ids.append(rule["rule_id"])
    driver.execute_query(
        SAVE_SCORE_SNAPSHOT,
        claim_id=result["claim_id"],
        snapshot_id=f"{result['claim_id']}-{as_of_date.isoformat()}",
        as_of_date=as_of_date.isoformat(),
        total_score=result["total_score"],
        band=result["band"],
        bi_score=scores["BI"],
        as_score=scores["AS"],
        bf_score=scores["BF"],
        ct_score=scores["CT"],
        nl_score=scores["NL"],
        coverage_pct=result["coverage_pct"],
        fired_rule_ids=fired_rule_ids,
        # default=str writes dates as text ("2024-03-05"); sort_keys keeps the text the same on every run.
        fired_rules_json=json.dumps(result["fired_rules"], default=str, sort_keys=True),
    )


def save_all_scores(driver, as_of_date=None):
    """Score every claim and save a snapshot for each. Return {band: number of claims}."""
    if as_of_date is None:
        as_of_date = datetime.date.today()
    records, _, _ = driver.execute_query(queries.ALL_CLAIM_IDS)
    claims_in_band = {}
    for record in records:
        result = score_facts(read_claim_facts(driver, record["claim_id"]))
        save_snapshot(driver, result, as_of_date)
        claims_in_band[result["band"]] = claims_in_band.get(result["band"], 0) + 1
    return claims_in_band


if __name__ == "__main__":
    from src.graph.connection import open_neo4j_driver

    graph_driver = open_neo4j_driver()
    try:
        band_counts = save_all_scores(graph_driver)
    finally:
        graph_driver.close()
    print(f"Saved a score for {sum(band_counts.values())} claims: {band_counts}")
