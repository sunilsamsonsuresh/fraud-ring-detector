"""Which structural rules really fire, computed from the finished tables.

The planners plant structure (shared phones, story groups, ring attorneys ...). This file
computes the result with the rule definitions, in plain Python, so the ground truth always
matches the data. The graph queries must give the same answer.

Strong link: two claims in DIFFERENT incidents that share (a) a phone, (b) an address,
(c) the same clinic AND the same attorney, or (d) the same law firm AND the same expert
(both claims have a lawsuit). A repeat claimant's claims share a phone, so they are
strongly linked too (the plan's definition, taken word for word).
"""

from src import config


def days_for_months(months):
    return round(months * 365 / 12)


def strong_link_kinds(first, second):
    """The kinds of strong link between two claim summaries (empty set = none)."""
    if first["incident_id"] == second["incident_id"]:
        return set()  # links inside one incident are not network evidence (rule 20)
    kinds = set()
    if first["phone"] == second["phone"]:
        kinds.add("phone")
    if first["address_id"] == second["address_id"]:
        kinds.add("address")
    if (
        first["attorney_id"]
        and first["clinic_id"] == second["clinic_id"]
        and first["attorney_id"] == second["attorney_id"]
    ):
        kinds.add("clinic_and_attorney")
    if (
        first["law_firm_id"]
        and first["law_firm_id"] == second["law_firm_id"]
        and first["expert_id"] == second["expert_id"]
    ):
        kinds.add("firm_and_expert")
    return kinds


def claim_summaries(tables):
    claimant_by_id = {row["claimant_id"]: row for row in tables["claimants"]}
    lawsuit_by_claim = {row["claim_id"]: row for row in tables["lawsuits"]}
    summaries = []
    for claim in tables["claims"]:
        claimant = claimant_by_id[claim["claimant_id"]]
        lawsuit = lawsuit_by_claim.get(claim["claim_id"])
        summaries.append(
            {
                "claim_id": claim["claim_id"],
                "incident_id": claim["incident_id"],
                "claimant_id": claim["claimant_id"],
                "loss_date": claim["loss_date"],
                "phone": claimant["phone_number"],
                "address_id": claimant["address_id"],
                "clinic_id": claim["clinic_id"],
                "attorney_id": claim["attorney_id"],
                "law_firm_id": lawsuit["plaintiff_law_firm_id"] if lawsuit else None,
                "expert_id": lawsuit["expert_id"] if lawsuit else None,
                "filed_date": lawsuit["filed_date"] if lawsuit else None,
            }
        )
    return summaries


def compute_structural_rules(tables, occupants_by_claim, story_group_by_claim):
    """{claim ID: set of fired rule IDs among AS-6 and NL-1 to NL-6}."""
    summaries = claim_summaries(tables)
    fired = {summary["claim_id"]: set() for summary in summaries}
    claims_per_incident = {}
    for summary in summaries:
        claims_per_incident[summary["incident_id"]] = (
            claims_per_incident.get(summary["incident_id"], 0) + 1
        )

    neighbours = {summary["claim_id"]: set() for summary in summaries}
    repeat_window = days_for_months(config.REPEAT_CLAIM_MONTHS)
    suit_window = days_for_months(config.FIRM_AND_EXPERT_MONTHS)
    for first in summaries:
        claim_id = first["claim_id"]
        occupants = occupants_by_claim.get(claim_id)
        if (
            occupants is not None
            and claims_per_incident[first["incident_id"]] > occupants
        ):
            fired[claim_id].add("AS-6")
        clinic_attorney_links = suit_links = repeat_claims = 0
        for second in summaries:
            if second is first:
                continue
            if (
                second["claimant_id"] == first["claimant_id"]
                and abs((second["loss_date"] - first["loss_date"]).days)
                <= repeat_window
            ):
                repeat_claims += 1
            group = story_group_by_claim.get(claim_id)
            if (
                group
                and group == story_group_by_claim.get(second["claim_id"])
                and first["incident_id"] != second["incident_id"]
            ):
                fired[claim_id].add("NL-4")
            kinds = strong_link_kinds(first, second)
            if not kinds:
                continue
            neighbours[claim_id].add(second["claim_id"])
            if "phone" in kinds or "address" in kinds:
                fired[claim_id].add("NL-1")
            if "clinic_and_attorney" in kinds:
                clinic_attorney_links += 1
            if (
                "firm_and_expert" in kinds
                and abs((second["filed_date"] - first["filed_date"]).days)
                <= suit_window
            ):
                suit_links += 1
        if repeat_claims >= config.REPEAT_CLAIM_OTHER_CLAIMS:
            fired[claim_id].add("NL-2")
        if clinic_attorney_links >= config.CLINIC_AND_ATTORNEY_MIN_CLAIMS:
            fired[claim_id].add("NL-3")
        if suit_links >= config.FIRM_AND_EXPERT_MIN_LAWSUITS:
            fired[claim_id].add("NL-5")

    for claim_id, fired_rule_ids in fired.items():
        if (
            len(claims_within_hops(neighbours, claim_id, config.CLUSTER_MAX_HOPS))
            >= config.CLUSTER_MIN_CLAIMS
        ):
            fired_rule_ids.add("NL-6")
    return fired


def claims_within_hops(neighbours, start_claim_id, max_hops):
    """The claims reachable from the start claim in max_hops strong links or fewer (start included)."""
    reached = {start_claim_id}
    frontier = [start_claim_id]
    for _ in range(max_hops):
        next_frontier = []
        for claim_id in frontier:
            for neighbour in neighbours[claim_id]:
                if neighbour not in reached:
                    reached.add(neighbour)
                    next_frontier.append(neighbour)
        frontier = next_frontier
    return reached


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.compute_network_truth      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    first = {
        "incident_id": "I-1",
        "phone": "713-555-0100",
        "address_id": "A-1",
        "clinic_id": "PR-1",
        "attorney_id": "AT-1",
        "law_firm_id": "LF-1",
        "expert_id": "EX-1",
    }
    second = dict(
        first, incident_id="I-2", address_id="A-2"
    )  # another incident, same phone
    same_incident = dict(first, address_id="A-3")
    print(
        "1. strong_link_kinds, other incident:",
        sorted(strong_link_kinds(first, second)),
    )
    print(
        "2. strong_link_kinds, same incident:",
        sorted(strong_link_kinds(first, same_incident)),
        "(rule 20: no evidence)",
    )

    neighbours = {
        "C-1": {"C-2"},
        "C-2": {"C-1", "C-3"},
        "C-3": {"C-2", "C-4"},
        "C-4": {"C-3"},
    }
    print(
        "3. claims_within_hops(C-1, 2):",
        sorted(claims_within_hops(neighbours, "C-1", 2)),
    )
    print("   days_for_months(12):", days_for_months(12))
