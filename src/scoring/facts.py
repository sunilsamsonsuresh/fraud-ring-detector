"""Read the facts of ONE claim from Neo4j (PLAN-v2.md V7, V8, V9).

read_raw_facts gives every fact WITH its date: table rows, all findings, the loss date of each
document and the network facts (src/graph/network.py). src/scoring/as_of.py then builds the
facts the rules read, either with everything (the current score) or only with what was
known on a given date (the score history). Dates are Python dates.
"""

from src.graph import queries
from src.graph.network import read_network_facts, rows_of


def read_raw_facts(driver, claim_id):
    """All facts of one claim as a dict, or None if the claim is not in the graph."""
    records, _, _ = driver.execute_query(queries.SCORING_CLAIM_FACTS, claim_id=claim_id)
    if not records:
        return None
    claim = rows_of(records)[0]

    policy = None
    if claim["policy_id"] is not None:
        policy = {}
        for key in ["policy_id", "effective_date", "expiration_date", "customer_since",
                    "last_coverage_increase_date", "lapse_start", "lapse_end"]:
            policy[key] = claim[key]

    # The earliest reported date of each claimant in the incident (a claimant may file twice).
    incident_claimants = {}
    for claimant_id, reported_date in claim["incident_claims"]:
        reported_date = reported_date.to_native() if hasattr(reported_date, "to_native") else reported_date
        if claimant_id not in incident_claimants or reported_date < incident_claimants[claimant_id]:
            incident_claimants[claimant_id] = reported_date

    def rows_from(query):
        query_records, _, _ = driver.execute_query(query, claim_id=claim_id)
        return rows_of(query_records)

    return {
        "claim_id": claim["claim_id"],
        "loss_date": claim["loss_date"],
        "reported_date": claim["reported_date"],
        "attorney_retained_date": claim["attorney_retained_date"],
        "repair_estimate_amount": claim["repair_estimate_amount"],
        "policy": policy,
        "incident_id": claim["incident_id"],
        "incident_claimants": incident_claimants if claim["incident_id"] is not None else None,
        "visit_dates": [row["visit_date"] for row in rows_from(queries.SCORING_VISIT_DATES)],
        "payments": rows_from(queries.SCORING_PAYMENTS),
        "reserve_events": rows_from(queries.SCORING_RESERVE_EVENTS),
        "lawsuits": rows_from(queries.SCORING_LAWSUITS),
        "document_loss_dates": rows_from(queries.SCORING_DOCUMENT_LOSS_DATES),
        "all_findings": rows_from(queries.FINDINGS_OF_CLAIM),
        "network": read_network_facts(driver, claim_id),
    }
