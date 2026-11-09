"""The fixed adjustments of the Challenger (PLAN-v2.md A8, V11). Plain code only.

The Challenger's checks (challenge_checks.py) find WHAT is affected. These functions apply
the fixed effect. The LLM never calls them and never changes points (CLAUDE.md, rule 19).

Adjustments on the raw facts (then the rules run again):
- same incident:  a link to a claim of the same incident is not network evidence.
- family link:    a phone or address link to a family member does not count for NL-1.
- busy provider:  a clinic-and-attorney (or firm-and-expert) link through a clinic (or firm) with more
                  than BUSY_PROVIDER_LIMIT claims does not count, unless the two claims share more.
Adjustments on the rule results:
- same proof twice: two fired rules rest on the same finding -> only the rule with more points counts.
- weak proof:       a rule that rests only on Low confidence findings does not count.
"""

import copy

from src import config
from src.scoring.rules_catalog import RULES_BY_ID

LINK_LISTS = ["direct_links", "cluster_links"]


def copy_with_network(raw):
    """A copy of raw whose network lists can be changed without touching the original."""
    adjusted = dict(raw)
    adjusted["network"] = copy.deepcopy(raw["network"])
    return adjusted


def drop_same_incident_links(raw, incident_claim_ids):
    """Remove every network fact that joins two claims of this claim's incident. The network templates
    already ignore such links, so this is a second safety check; it normally removes nothing."""
    adjusted = copy_with_network(raw)
    network = adjusted["network"]
    incident_group = set(incident_claim_ids) | {raw["claim_id"]}
    removed = set()
    for list_name in LINK_LISTS:
        kept = []
        for link in network[list_name]:
            if link["source_claim_id"] in incident_group and link["linked_claim_id"] in incident_group:
                removed.add(link["linked_claim_id"])
            else:
                kept.append(link)
        network[list_name] = kept
    for list_name, key in [("repeat_claims", "claim_id"), ("copied_story", "other_claim_id")]:
        kept = []
        for item in network[list_name]:
            if item[key] in incident_claim_ids:
                removed.add(item[key])
            else:
                kept.append(item)
        network[list_name] = kept
    removed.discard(raw["claim_id"])
    return adjusted, sorted(removed)


def drop_family_links(raw, family_claim_ids):
    """Remove the phone and address links to family members, so they do not fire NL-1."""
    adjusted = copy_with_network(raw)
    kept, removed = [], set()
    for link in adjusted["network"]["direct_links"]:
        if link["kind"] in ["phone", "address"] and link["linked_claim_id"] in family_claim_ids:
            removed.add(link["linked_claim_id"])
        else:
            kept.append(link)
    adjusted["network"]["direct_links"] = kept
    return adjusted, sorted(removed)


def link_kinds_by_pair(links):
    """{(claim, other claim): set of link kinds}, in both directions."""
    kinds = {}
    for link in links:
        for pair in [(link["source_claim_id"], link["linked_claim_id"]), (link["linked_claim_id"], link["source_claim_id"])]:
            kinds.setdefault(pair, set()).add(link["kind"])
    return kinds


def is_busy_provider_link(link, kinds_by_pair, copied_claim_ids):
    if link["kind"] not in ["clinic_and_attorney", "firm_and_expert"]:
        return False
    if (link["provider_claim_count"] or 0) <= config.BUSY_PROVIDER_LIMIT:
        return False
    pair = (link["source_claim_id"], link["linked_claim_id"])
    other_kinds = kinds_by_pair[pair] - {link["kind"]}
    return not other_kinds and link["linked_claim_id"] not in copied_claim_ids


def drop_busy_provider_links(raw):
    """Remove links that rest only on a busy clinic (or law firm) and its attorney (or expert)."""
    adjusted = copy_with_network(raw)
    network = adjusted["network"]
    kinds_by_pair = link_kinds_by_pair(network["cluster_links"])
    copied_claim_ids = {copy_item["other_claim_id"] for copy_item in network["copied_story"]}
    removed = set()
    for list_name in LINK_LISTS:
        kept = []
        for link in network[list_name]:
            if is_busy_provider_link(link, kinds_by_pair, copied_claim_ids):
                first, second = sorted([link["source_claim_id"], link["linked_claim_id"]])
                removed.add(f"{first} and {second} ({link['shared_value']}, {link['provider_claim_count']} claims)")
            else:
                kept.append(link)
        network[list_name] = kept
    return adjusted, sorted(removed)


def not_counted(rule_result, reason):
    proof = dict(rule_result["proof"])
    proof["not_counted"] = reason
    return {"status": "not_fired", "proof": proof}


def drop_same_proof_twice(rule_results):
    """Two fired rules on the same finding: keep the one with more points. Return (results, dropped rule IDs)."""
    rules_by_finding = {}
    for rule_id, result in rule_results.items():
        if result["status"] == "fired":
            for finding in result["proof"].get("findings", []):
                rules_by_finding.setdefault(finding["finding_id"], []).append(rule_id)
    adjusted = dict(rule_results)
    dropped = []
    for finding_id, rule_ids in sorted(rules_by_finding.items()):
        if len(rule_ids) < 2:
            continue
        ordered = sorted(rule_ids, key=lambda rule_id: (-RULES_BY_ID[rule_id].points, rule_id))
        for rule_id in ordered[1:]:
            if adjusted[rule_id]["status"] == "fired":
                adjusted[rule_id] = not_counted(adjusted[rule_id], f"same finding {finding_id} as {ordered[0]}")
                dropped.append(rule_id)
    return adjusted, dropped


def drop_weak_proof(rule_results):
    """A fired rule whose findings are all Low confidence does not count. Return (results, dropped rule IDs)."""
    adjusted = dict(rule_results)
    dropped = []
    for rule_id, result in rule_results.items():
        findings = result["proof"].get("findings", [])
        if result["status"] == "fired" and findings and all(item["confidence"] == "Low" for item in findings):
            adjusted[rule_id] = not_counted(result, "rests only on Low confidence findings")
            dropped.append(rule_id)
    return adjusted, dropped
