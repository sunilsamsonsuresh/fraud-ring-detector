"""Read the facts of ONE claim that the scoring rules need.

A rule is a plain function: facts in, yes or no out. So the rules never touch the database.
This file is the only place where the scoring reads the graph. It gives the rules a dict.

Dates are Python dates here (not text), because the rules do date arithmetic. Example: the days
between the loss date and a visit. The dict holds only what the rules written so far need.
When a new rule needs a new fact, we add it here.
"""

from src import config
from src.graph import queries
from src.scoring.findings import usable_and_weak_findings
from src.tools.claim_tools import rows_from
from src.tools.link_tools import (
    claim_has_story_text,
    find_cluster,
    find_copied_story,
    find_direct_links,
)


def to_date(value):
    """A Neo4j date as a Python date (datetime.date). None stays None."""
    if value is None:
        return None
    return value.to_native()


def read_claim_facts(driver, claim_id):
    """The facts of one claim, or None when the claim is not in the graph.

    The claim ID must be checked before (src/tools/checks.py)."""
    claim_rows = rows_from(driver, queries.CLAIM_AND_POLICY, claim_id)
    if not claim_rows:
        return None
    claim = claim_rows[0]

    # The query sorts the visits by date.
    visit_dates = [
        to_date(row["visit_date"])
        for row in rows_from(driver, queries.CLAIM_VISIT_DATES, claim_id)
    ]

    # A claim may have no policy in the graph. The rules then say "not evaluated".
    policy = None
    if claim["policy_id"] is not None:
        policy = {}
        for key in [
            "effective_date",
            "expiration_date",
            "customer_since",
            "last_coverage_increase_date",
            "lapse_start",
            "lapse_end",
        ]:
            policy[key] = to_date(claim[key])

    lawsuits = []
    for row in rows_from(driver, queries.CLAIM_LAWSUITS, claim_id):
        lawsuits.append(
            {
                "lawsuit_id": row["lawsuit_id"],
                "filed_date": to_date(row["filed_date"]),
                "limitation_deadline": to_date(row["limitation_deadline"]),
            }
        )

    # Both queries sort by date, so the first and last item are the oldest and the newest.
    payments = []
    for row in rows_from(driver, queries.CLAIM_PAYMENTS, claim_id):
        payments.append(
            {
                "payment_id": row["payment_id"],
                "payment_date": to_date(row["payment_date"]),
                "amount": row["amount"],
                "payment_type": row["payment_type"],
            }
        )
    reserve_events = []
    for row in rows_from(driver, queries.CLAIM_RESERVE_EVENTS, claim_id):
        reserve_events.append(
            {
                "event_id": row["event_id"],
                "event_date": to_date(row["event_date"]),
                "reserve_total": row["reserve_total"],
            }
        )

    document_loss_dates = []
    for row in rows_from(driver, queries.CLAIM_DOCUMENT_LOSS_DATES, claim_id):
        document_loss_dates.append(
            {
                "document_id": row["document_id"],
                "document_type": row["document_type"],
                "loss_date_in_pdf": to_date(row["loss_date_in_pdf"]),
                "page_number": row["page_number"],
            }
        )

    # The firm-and-expert links carry the filed dates of both suits (NL-5). Other kinds have none.
    direct_links = find_direct_links(driver, claim_id)
    for link in direct_links:
        if "source_filed_date" in link:
            link["source_filed_date"] = to_date(link["source_filed_date"])
            link["linked_filed_date"] = to_date(link["linked_filed_date"])

    repeat_claims = []
    for row in rows_from(driver, queries.REPEAT_CLAIMS_OF_CLAIMANT, claim_id):
        repeat_claims.append(
            {"claim_id": row["claim_id"], "loss_date": to_date(row["loss_date"])}
        )

    # A claim with no incident has no claimant count. AS-6 then says "not evaluated".
    incident_id = claim["incident_id"]
    incident_claimant_count = None
    for row in rows_from(driver, queries.INCIDENT_CLAIMANT_COUNT, claim_id):
        incident_claimant_count = row["claimants_in_incident"]

    findings, weak_findings = usable_and_weak_findings(driver, claim_id)

    return {
        "claim_id": claim_id,
        "loss_date": to_date(claim["loss_date"]),
        "reported_date": to_date(claim["reported_date"]),
        "attorney_retained_date": to_date(claim["attorney_retained_date"]),
        "repair_estimate_amount": claim["repair_estimate_amount"],
        "policy": policy,
        "document_loss_dates": document_loss_dates,
        "payments": payments,
        "reserve_events": reserve_events,
        "visit_dates": visit_dates,
        "lawsuits": lawsuits,
        "direct_links": direct_links,
        "repeat_claims": repeat_claims,
        "incident_id": incident_id,
        "incident_claimant_count": incident_claimant_count,
        "has_story_text": claim_has_story_text(driver, claim_id),
        "copied_story": find_copied_story(driver, claim_id),
        "findings": findings,
        "weak_findings": weak_findings,
        "cluster_claim_ids": find_cluster(driver, claim_id, config.CLUSTER_MAX_HOPS),
    }
