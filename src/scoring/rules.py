"""The yes/no check of each rule (PLAN-v2.md A7, V7). One plain function per rule.

Each check reads the facts of ONE claim (src/scoring/facts.py) and returns:
  {"status": "fired" | "not_fired" | "not_evaluated", "proof": {...}}
"not_evaluated" means an input is missing. The rule then counts as not fired, and its
points do not count toward coverage. The proof names table values or finding IDs, so a
human can check every answer. No LLM call happens here (CLAUDE.md, rules 16 and 18).

Notes rules read the merged findings with Medium or High confidence only (A6, rule 5).
NL rules read the network facts (V8); links inside one incident never count.
"""

from src import config


def fired_or_not(is_fired, proof):
    return {"status": "fired" if is_fired else "not_fired", "proof": proof}


def not_evaluated(reason):
    return {"status": "not_evaluated", "proof": {"missing": reason}}


def finding_proof(finding):
    return {"finding_id": finding["finding_id"], "value": finding["value"], "confidence": finding["confidence"],
            "document_id": finding["document_id"], "page_number": finding["page_number"], "quote": finding["quote"]}


def feature_rule(facts, feature_code, firing_values):
    """The common check of a notes rule: does the merged finding have a firing value?"""
    finding = facts["findings"].get(feature_code)
    if finding is None:
        return not_evaluated(f"no {feature_code} finding with {config.MIN_CONFIDENCE} confidence or higher")
    return fired_or_not(finding["value"] in firing_values, {"findings": [finding_proof(finding)]})


# --- BI: Bodily Injury and Treatment ---

def check_bi_1(facts):
    return feature_rule(facts, "injury_crash_fit", ["Inconsistent"])


def check_bi_2(facts):
    return feature_rule(facts, "treatment_growth", ["Disproportionate", "Extreme"])


def check_bi_3(facts):
    return feature_rule(facts, "objective_support", ["Predominantly subjective", "Contradicted"])


def check_bi_4(facts):
    return feature_rule(facts, "pre_existing_condition", ["Material", "Predominant"])


def check_bi_5(facts):
    if facts["attorney_retained_date"] is None:
        return not_evaluated("no attorney on the claim")
    if not facts["visit_dates"]:
        return not_evaluated("no treatment visits")
    first_visit = facts["visit_dates"][0]
    return fired_or_not(facts["attorney_retained_date"] < first_visit,
                        {"attorney_retained_date": facts["attorney_retained_date"], "first_visit_date": first_visit})


def check_bi_6(facts):
    early_visits = 0
    for visit_date in facts["visit_dates"]:
        if 0 <= (visit_date - facts["loss_date"]).days <= config.HEAVY_EARLY_TREATMENT_DAYS:
            early_visits += 1
    return fired_or_not(early_visits > config.HEAVY_EARLY_TREATMENT_VISITS,
                        {"loss_date": facts["loss_date"],
                         f"visits_in_first_{config.HEAVY_EARLY_TREATMENT_DAYS}_days": early_visits})


# --- AS: Accident Staging ---

def check_as_1(facts):
    return feature_rule(facts, "occurrence_support", ["Uncorroborated"])


def check_as_2(facts):
    return feature_rule(facts, "occurrence_support", ["Contradicted", "Suspected staged"])


def check_as_3(facts):
    return feature_rule(facts, "damage_crash_fit", ["Inconsistent"])


def check_as_4(facts):
    return feature_rule(facts, "account_stability", ["Materially changed"])


def check_as_5(facts):
    return feature_rule(facts, "occupant_presence", ["Added later", "Not present"])


def check_as_6(facts):
    finding = facts["findings"].get("occupants_listed")
    if finding is None:
        return not_evaluated(f"no occupants_listed finding with {config.MIN_CONFIDENCE} confidence or higher")
    if facts["incident_claimant_count"] is None:
        return not_evaluated("the claim has no incident")
    return fired_or_not(facts["incident_claimant_count"] > finding["value"],
                        {"incident_id": facts["incident_id"], "claimants_in_incident": facts["incident_claimant_count"],
                         "findings": [finding_proof(finding)]})


def check_as_7(facts):
    documents = [document for document in facts["document_loss_dates"] if document["loss_date_in_pdf"] is not None]
    if not documents:
        return not_evaluated("no document states a loss date")
    conflicts = []
    for document in documents:
        if document["conflict"]:
            conflicts.append(f"{document['document_id']} page {document['page_number']}: "
                             f"{document['loss_date_in_pdf']}")
    return fired_or_not(len(conflicts) > 0, {"table_loss_date": facts["loss_date"],
                                             "documents_checked": len(documents), "conflicts": conflicts})


# --- BF: Billing and Expense ---

def check_bf_1(facts):
    events = facts["reserve_events"]
    if not events:
        return not_evaluated("no reserve history")
    for first_index, first in enumerate(events):
        for later in events[first_index + 1:]:
            within_window = (later["event_date"] - first["event_date"]).days <= config.RESERVE_RISE_DAYS
            if within_window and later["reserve_total"] > first["reserve_total"] * (1 + config.RESERVE_RISE_SHARE):
                return fired_or_not(True, {"from_event": f"{first['event_id']} {first['event_date']} "
                                                         f"{first['reserve_total']:.2f}",
                                           "to_event": f"{later['event_id']} {later['event_date']} "
                                                       f"{later['reserve_total']:.2f}"})
    return fired_or_not(False, {"reserve_events": len(events)})


def check_bf_2(facts):
    if not facts["reserve_events"]:
        return not_evaluated("no reserve history")
    latest = facts["reserve_events"][-1]
    total_paid = round(sum(payment["amount"] for payment in facts["payments"]), 2)
    return fired_or_not(total_paid >= config.PAID_TO_RESERVE_RATIO * latest["reserve_total"],
                        {"total_paid": total_paid, "latest_reserve": latest["reserve_total"],
                         "latest_reserve_event": latest["event_id"]})


def check_bf_3(facts):
    payments = facts["payments"]
    group_size = config.PAYMENT_CLUSTER_COUNT
    for index in range(len(payments) - group_size + 1):
        group = payments[index:index + group_size]
        if (group[-1]["payment_date"] - group[0]["payment_date"]).days <= config.PAYMENT_CLUSTER_DAYS:
            return fired_or_not(True, {"payments": [f"{payment['payment_id']} {payment['payment_date']}"
                                                    for payment in group]})
    return fired_or_not(False, {"payments": len(payments)})


def check_bf_4(facts):
    if facts["repair_estimate_amount"] is None:
        return not_evaluated("no repair estimate")
    repair_paid = round(sum(payment["amount"] for payment in facts["payments"]
                            if payment["payment_type"] == "repair"), 2)
    return fired_or_not(repair_paid >= config.REPAIR_GROWTH_RATIO * facts["repair_estimate_amount"],
                        {"repair_paid": repair_paid, "repair_estimate_amount": facts["repair_estimate_amount"]})


def check_bf_5(facts):
    return feature_rule(facts, "duplicate_billing", ["Confirmed"])


def check_bf_6(facts):
    return feature_rule(facts, "labor_hours_plausibility", ["Excessive"])


# --- CT: Coverage Trigger ---

def check_ct_1(facts):
    policy = facts["policy"]
    if policy is None or policy["customer_since"] is None:
        return not_evaluated("no customer_since date")
    days = (facts["loss_date"] - policy["customer_since"]).days
    return fired_or_not(days < config.NEW_CUSTOMER_DAYS, {"customer_since": policy["customer_since"],
                                                          "loss_date": facts["loss_date"], "days": days})


def check_ct_2(facts):
    policy = facts["policy"]
    if policy is None:
        return not_evaluated("no policy")
    increase_date = policy["last_coverage_increase_date"]
    if increase_date is None:      # the table says: no coverage increase, so the rule is checked and quiet
        return fired_or_not(False, {"last_coverage_increase_date": None})
    days = (facts["loss_date"] - increase_date).days
    return fired_or_not(0 <= days <= config.COVERAGE_INCREASE_DAYS,
                        {"last_coverage_increase_date": increase_date, "loss_date": facts["loss_date"], "days": days})


def check_ct_3(facts):
    policy = facts["policy"]
    if policy is None or policy["effective_date"] is None or policy["expiration_date"] is None:
        return not_evaluated("no policy dates")
    loss_date = facts["loss_date"]
    outside_term = loss_date < policy["effective_date"] or loss_date > policy["expiration_date"]
    in_lapse = policy["lapse_start"] is not None and policy["lapse_start"] <= loss_date <= policy["lapse_end"]
    return fired_or_not(outside_term or in_lapse,
                        {"loss_date": loss_date, "effective_date": policy["effective_date"],
                         "expiration_date": policy["expiration_date"], "lapse_start": policy["lapse_start"],
                         "lapse_end": policy["lapse_end"]})


def check_ct_4(facts):
    days = (facts["reported_date"] - facts["loss_date"]).days
    return fired_or_not(days > config.LATE_REPORT_DAYS, {"loss_date": facts["loss_date"],
                                                         "reported_date": facts["reported_date"], "days": days})


def check_ct_5(facts):
    prior = facts["findings"].get("prior_damage_evidence")
    known = facts["findings"].get("known_loss_evidence")
    if prior is None and known is None:
        return not_evaluated("no prior_damage_evidence or known_loss_evidence finding with "
                             f"{config.MIN_CONFIDENCE} confidence or higher")
    prior_fires = prior is not None and prior["value"] in ["Documented", "Material"]
    known_fires = known is not None and known["value"] == "Strong"
    findings = [finding_proof(finding) for finding in [prior, known] if finding is not None]
    return fired_or_not(prior_fires or known_fires, {"findings": findings})


def check_ct_6(facts):
    return feature_rule(facts, "driver_status", ["Unlisted", "Excluded"])


def check_ct_7(facts):
    if not facts["lawsuits"]:
        return not_evaluated("no lawsuit")
    for lawsuit in facts["lawsuits"]:
        days = (lawsuit["limitation_deadline"] - lawsuit["filed_date"]).days
        if 0 <= days <= config.SUIT_NEAR_DEADLINE_DAYS:
            return fired_or_not(True, {"lawsuit_id": lawsuit["lawsuit_id"], "filed_date": lawsuit["filed_date"],
                                       "limitation_deadline": lawsuit["limitation_deadline"], "days": days})
    first = facts["lawsuits"][0]
    return fired_or_not(False, {"lawsuit_id": first["lawsuit_id"], "filed_date": first["filed_date"],
                                "limitation_deadline": first["limitation_deadline"]})


# --- NL: Network Links (V8). The facts come from the fixed templates in src/graph/network.py,
# which already ignore links inside one incident. ---

MAX_CLAIMS_IN_PROOF = 10


def days_for_months(months):
    """The same month length as the data generator: 12 months = 365 days."""
    return round(months * 365 / 12)


def links_of_kind(facts, kinds):
    return [link for link in facts["strong_links"] if link["kind"] in kinds]


def link_texts(links):
    texts = sorted({f"{link['linked_claim_id']} ({link['kind']}: {link['shared_value']})" for link in links})
    return texts[:MAX_CLAIMS_IN_PROOF]


def check_nl_1(facts):
    links = links_of_kind(facts, ["phone", "address"])
    return fired_or_not(len(links) > 0, {"links": link_texts(links)})


def check_nl_2(facts):
    window = days_for_months(config.REPEAT_CLAIM_MONTHS)
    others = []
    for other in facts["repeat_claims"]:
        if abs((other["loss_date"] - facts["loss_date"]).days) <= window:
            others.append(f"{other['claim_id']} (loss {other['loss_date']})")
    return fired_or_not(len(others) >= config.REPEAT_CLAIM_OTHER_CLAIMS, {"other_claims_of_claimant": others})


def check_nl_3(facts):
    if facts["attorney_retained_date"] is None:
        return not_evaluated("no attorney on the claim")
    links = links_of_kind(facts, ["clinic_and_attorney"])
    linked_claims = {link["linked_claim_id"] for link in links}
    return fired_or_not(len(linked_claims) >= config.CLINIC_AND_ATTORNEY_MIN_CLAIMS,
                        {"linked_claim_count": len(linked_claims), "links": link_texts(links)})


def check_nl_4(facts):
    if not facts["has_story_text"]:
        return not_evaluated("no story text chunks (run ingest-documents --chunks)")
    copies = facts["copied_story"]
    pairs = []
    for copy in copies[:MAX_CLAIMS_IN_PROOF]:
        pairs.append(f"{copy['document_id']} page {copy['page_number']} ~ {copy['other_document_id']} "
                     f"page {copy['other_page_number']} ({copy['score']:.3f})")
    return fired_or_not(len(copies) > 0, {"other_claims": sorted({copy["other_claim_id"] for copy in copies}),
                                          "copied_chunks": pairs})


def check_nl_5(facts):
    if not facts["lawsuits"]:
        return not_evaluated("no lawsuit")
    window = days_for_months(config.FIRM_AND_EXPERT_MONTHS)
    linked_claims = set()
    for link in links_of_kind(facts, ["firm_and_expert"]):
        if abs((link["linked_filed_date"] - link["source_filed_date"]).days) <= window:
            linked_claims.add(link["linked_claim_id"])
    return fired_or_not(len(linked_claims) >= config.FIRM_AND_EXPERT_MIN_LAWSUITS,
                        {"lawsuits_within_window": len(linked_claims), "linked_claims": sorted(linked_claims)})


def check_nl_6(facts):
    cluster = facts["cluster_claim_ids"]
    return fired_or_not(len(cluster) >= config.CLUSTER_MIN_CLAIMS,
                        {"claims_in_group": len(cluster), "claims": cluster[:MAX_CLAIMS_IN_PROOF]})


RULE_CHECKS = {
    "BI-1": check_bi_1, "BI-2": check_bi_2, "BI-3": check_bi_3, "BI-4": check_bi_4, "BI-5": check_bi_5,
    "BI-6": check_bi_6,
    "AS-1": check_as_1, "AS-2": check_as_2, "AS-3": check_as_3, "AS-4": check_as_4, "AS-5": check_as_5,
    "AS-6": check_as_6, "AS-7": check_as_7,
    "BF-1": check_bf_1, "BF-2": check_bf_2, "BF-3": check_bf_3, "BF-4": check_bf_4, "BF-5": check_bf_5,
    "BF-6": check_bf_6,
    "CT-1": check_ct_1, "CT-2": check_ct_2, "CT-3": check_ct_3, "CT-4": check_ct_4, "CT-5": check_ct_5,
    "CT-6": check_ct_6, "CT-7": check_ct_7,
    "NL-1": check_nl_1, "NL-2": check_nl_2, "NL-3": check_nl_3, "NL-4": check_nl_4, "NL-5": check_nl_5,
    "NL-6": check_nl_6,
}
