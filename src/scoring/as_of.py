"""The facts as they were known on a date (PLAN-v2.md V9). No look-ahead.

facts_as_of(raw, as_of_date) keeps only the facts dated on or before as_of_date.
as_of_date = None keeps everything (the current score).

When is a fact known?
- Visits, payments, reserve events: on their own date. A lawsuit: on its filed date.
- The attorney: on attorney_retained_date.
- Other claims (incident claimants, network links, repeat claims): on their reported date.
- A finding: on its document's date (below), or on its note date if that is later.
- Documents carry no date of their own, so plain code uses the earliest date the document
  can exist (DOCUMENT_KNOWN_FROM). Example: a medical treatment summary covers all visits,
  so it is known from the last visit date.
Nothing is known before the claim is reported, so every date is moved up to the reported date.
"""

from src import config
from src.documents.feature_extraction import merge_findings
from src.graph.network import claims_within_hops

# document type -> the claim date from which it can exist
DOCUMENT_KNOWN_FROM = {
    "fnol": "reported_date", "police_report": "reported_date", "repair_estimate": "reported_date",
    "adjuster_file": "reported_date", "medical_records": "last_visit_date",
    "attorney_letter": "attorney_retained_date", "demand_letter": "attorney_retained_date",
    "complaint": "filed_date", "defense_answer": "filed_date", "deposition": "filed_date",
    "settlement_agreement": "settlement_date",
}


def claim_dates(raw):
    first_lawsuit = raw["lawsuits"][0] if raw["lawsuits"] else {}
    return {"reported_date": raw["reported_date"],
            "last_visit_date": raw["visit_dates"][-1] if raw["visit_dates"] else None,
            "attorney_retained_date": raw["attorney_retained_date"],
            "filed_date": first_lawsuit.get("filed_date"),
            "settlement_date": first_lawsuit.get("settlement_date") or first_lawsuit.get("filed_date")}


def known_from(document_type, raw, note_date=None):
    """The first date a fact from this document type is known."""
    dates = claim_dates(raw)
    document_date = dates.get(DOCUMENT_KNOWN_FROM.get(document_type, "reported_date")) or raw["reported_date"]
    known = max(document_date, raw["reported_date"])
    if note_date is not None:
        known = max(known, note_date)
    return known


def is_known(fact_date, as_of_date):
    return as_of_date is None or (fact_date is not None and fact_date <= as_of_date)


def is_strong_enough(finding):
    levels = config.CONFIDENCE_LEVELS
    return finding["confidence"] in levels and levels.index(finding["confidence"]) >= levels.index(config.MIN_CONFIDENCE)


def findings_as_of(raw, as_of_date):
    """(merged Medium-or-higher findings, weak findings) known on the date."""
    strong, weak = [], []
    for finding in raw["all_findings"]:
        if not is_known(known_from(finding["document_type"], raw, finding["note_date"]), as_of_date):
            continue
        if is_strong_enough(finding):
            strong.append(finding)
        else:
            weak.append(finding)
    return merge_findings(strong), weak


def link_is_known(link, as_of_date):
    """A strong link exists once the other claim is reported. A firm-and-expert link also
    needs both lawsuits filed."""
    if not is_known(link["linked_reported_date"], as_of_date):
        return False
    if link["kind"] == "firm_and_expert":
        return is_known(link["source_filed_date"], as_of_date) and is_known(link["linked_filed_date"], as_of_date)
    return True


def network_as_of(raw, as_of_date):
    """The network facts the NL rules read, with only the other claims reported by the date."""
    network = raw["network"]
    claim_id = raw["claim_id"]
    direct_links = [link for link in network["direct_links"] if link_is_known(link, as_of_date)]
    known_links = [link for link in network["cluster_links"] if link_is_known(link, as_of_date)]
    allowed = None
    if as_of_date is not None:
        allowed = {other for other, reported in network["reported_dates"].items() if is_known(reported, as_of_date)}
    cluster = claims_within_hops(known_links, claim_id, config.CLUSTER_MAX_HOPS, allowed)
    copied = []
    for copy in network["copied_story"]:
        own_known = known_from(copy["document_type"], raw)
        if is_known(own_known, as_of_date) and is_known(copy["other_reported_date"], as_of_date):
            copied.append(copy)
    story_types = [kind for kind in network["story_document_types"] if is_known(known_from(kind, raw), as_of_date)]
    return {
        "strong_links": direct_links,
        "repeat_claims": [other for other in network["repeat_claims"] if is_known(other["reported_date"], as_of_date)],
        "copied_story": copied,
        "has_story_text": len(story_types) > 0,
        "cluster_claim_ids": sorted(cluster),
    }


def facts_as_of(raw, as_of_date=None):
    """The facts the rules read (see src/scoring/rules.py), known on as_of_date (None = all)."""
    findings, weak_findings = findings_as_of(raw, as_of_date)
    incident_claimant_count = None
    if raw["incident_claimants"] is not None:
        incident_claimant_count = 0
        for reported_date in raw["incident_claimants"].values():
            if is_known(reported_date, as_of_date):
                incident_claimant_count += 1
    documents = [document for document in raw["document_loss_dates"]
                 if is_known(known_from(document["document_type"], raw), as_of_date)]
    retained = raw["attorney_retained_date"]
    facts = {
        "claim_id": raw["claim_id"], "loss_date": raw["loss_date"], "reported_date": raw["reported_date"],
        "attorney_retained_date": retained if is_known(retained, as_of_date) else None,
        "repair_estimate_amount": raw["repair_estimate_amount"], "policy": raw["policy"],
        "incident_id": raw["incident_id"], "incident_claimant_count": incident_claimant_count,
        "visit_dates": [visit for visit in raw["visit_dates"] if is_known(visit, as_of_date)],
        "payments": [payment for payment in raw["payments"] if is_known(payment["payment_date"], as_of_date)],
        "reserve_events": [event for event in raw["reserve_events"] if is_known(event["event_date"], as_of_date)],
        "lawsuits": [lawsuit for lawsuit in raw["lawsuits"] if is_known(lawsuit["filed_date"], as_of_date)],
        "document_loss_dates": documents,
        "findings": findings,
        "weak_findings": weak_findings,
    }
    facts.update(network_as_of(raw, as_of_date))
    return facts
