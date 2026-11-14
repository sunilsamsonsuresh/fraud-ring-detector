"""Plain-code tools that read ONE claim from the graph. No LLM is called here.

A tool is a plain function: it gets a driver and checked values, and it returns a dict.
Later, the MCP server will offer these functions to the agents.

Every tool returns one of two shapes:
  {"facts": ..., "notes": [...], "sources": [...]}   the answer, with where it came from
  {"message": "..."}                                 there is nothing to show, and why

The sources are the evidence. Each fact must be traceable to the graph (CLAUDE.md, rule 12).
"""

from src.graph import queries


def iso_date(value):
    """A Neo4j date as text like "2024-12-15". None stays None. Text is easy to send as JSON."""
    if value is None:
        return None
    return value.iso_format()


def rows_from(driver, query, claim_id):
    records, _, _ = driver.execute_query(query, claim_id=claim_id)
    return [record.data() for record in records]


def get_claim_record(driver, claim_id):
    """The data of one claim as it is stored: dates, visits, payments, reserve, lawsuits.

    It does not judge anything. The scoring rules do that, in a later file."""
    claim_rows = rows_from(driver, queries.CLAIM_AND_POLICY, claim_id)
    if not claim_rows:
        return {"message": f"Claim {claim_id} was not found in the graph."}
    claim = claim_rows[0]

    policy = None
    if claim["policy_id"] is not None:
        policy = {
            "policy_id": claim["policy_id"],
            "effective_date": iso_date(claim["effective_date"]),
            "expiration_date": iso_date(claim["expiration_date"]),
            "customer_since": iso_date(claim["customer_since"]),
            "last_coverage_increase_date": iso_date(
                claim["last_coverage_increase_date"]
            ),
            "lapse_start": iso_date(claim["lapse_start"]),
            "lapse_end": iso_date(claim["lapse_end"]),
        }

    # The query sorts the visits by date, so the first and last item are the first and last visit.
    visit_dates = [
        iso_date(row["visit_date"])
        for row in rows_from(driver, queries.CLAIM_VISIT_DATES, claim_id)
    ]
    treatment = {
        "visit_count": len(visit_dates),
        "first_visit_date": visit_dates[0] if visit_dates else None,
        "last_visit_date": visit_dates[-1] if visit_dates else None,
    }

    payments = rows_from(driver, queries.CLAIM_PAYMENTS, claim_id)
    total_paid = 0.0
    for payment in payments:
        total_paid += payment["amount"]

    reserve_events = [
        {
            "event_date": iso_date(row["event_date"]),
            "reserve_total": row["reserve_total"],
        }
        for row in rows_from(driver, queries.CLAIM_RESERVE_EVENTS, claim_id)
    ]
    reserve = {
        "event_count": len(reserve_events),
        "first_reserve": reserve_events[0] if reserve_events else None,
        "latest_reserve": reserve_events[-1] if reserve_events else None,
    }

    lawsuits = [
        {
            "lawsuit_id": row["lawsuit_id"],
            "filed_date": iso_date(row["filed_date"]),
            "limitation_deadline": iso_date(row["limitation_deadline"]),
            "settlement_date": iso_date(row["settlement_date"]),
        }
        for row in rows_from(driver, queries.CLAIM_LAWSUITS, claim_id)
    ]

    facts = {
        "claim_id": claim_id,
        "loss_date": iso_date(claim["loss_date"]),
        "reported_date": iso_date(claim["reported_date"]),
        "attorney_retained_date": iso_date(claim["attorney_retained_date"]),
        "repair_estimate_amount": claim["repair_estimate_amount"],
        "incident_id": claim["incident_id"],
        "policy": policy,
        "treatment": treatment,
        "payments": {
            "payment_count": len(payments),
            "total_paid": round(total_paid, 2),
        },
        "reserve": reserve,
        "lawsuits": lawsuits,
    }
    return {
        "facts": facts,
        "notes": ["The values are stored data. They are not a judgement."],
        "sources": [
            f"Claim, Policy, Treatment, Payment, ReserveEvent and Lawsuit nodes of {claim_id}"
        ],
    }


MAX_QUOTE_CHARACTERS = 300  # a long quote would fill the prompt of an agent


def get_claim_findings(driver, claim_id):
    """What the documents of one claim say, as rated findings: feature, rating, confidence, quote, page.

    A finding was read from a PDF page when the graph was built. Its quote is on that page (checked then)."""
    if not rows_from(driver, queries.CLAIM_EXISTS, claim_id):
        return {"message": f"Claim {claim_id} was not found in the graph."}
    rows = rows_from(driver, queries.CLAIM_FINDINGS, claim_id)
    if not rows:
        return {"message": f"Claim {claim_id} has no findings from its documents."}

    # The most serious ratings first, so a cut list still shows what matters.
    rows.sort(key=lambda row: (-int(row["severity_rank"] or 0), row["feature"]))
    findings = []
    for row in rows:
        findings.append(
            {
                "feature": row["feature"],
                "rating": row["value"],
                "confidence": row["confidence"],
                "quote": (row["quote"] or "")[:MAX_QUOTE_CHARACTERS],
                "document_id": row["document_id"],
                "page_number": row["page_number"],
            }
        )
    return {
        "facts": {
            "claim_id": claim_id,
            "finding_count": len(findings),
            "findings": findings,
        },
        "notes": [
            "A finding is what a document says, rated when the graph was built. It is not a judgement.",
            "Low-confidence findings are listed, but no scoring rule uses them.",
        ],
        # dict.fromkeys keeps the first of each page and drops the repeats, in order.
        "sources": list(
            dict.fromkeys(
                f"{row['document_id']}, page {row['page_number']}" for row in findings
            )
        ),
    }
