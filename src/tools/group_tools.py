"""Plain-code tool: groups of claims that share something, across ALL claims. No LLM is called here.

It answers questions with no claim ID, for example "Are there claims that share the same address?".
The other link tools start from one claim. This one looks at the whole graph.

The kind of group is checked before (src/tools/checks.py, check_group_kind). Each kind has its own
named query in src/graph/queries.py, so no query text is ever built from a value.
A group is a possible link that needs human review. It is never proof (CLAUDE.md, rule 14).
"""

from src import config
from src.graph import queries

# kind -> (the query, the smallest group). The smallest groups come from config.py.
GROUP_QUERIES = {
    "phone": (queries.GROUPS_SHARED_PHONE, config.SHARED_CONTACT_MIN_CLAIMS),
    "address": (queries.GROUPS_SHARED_ADDRESS, config.SHARED_CONTACT_MIN_CLAIMS),
    "clinic_and_attorney": (
        queries.GROUPS_CLINIC_AND_ATTORNEY,
        config.CLINIC_AND_ATTORNEY_MIN_CLAIMS,
    ),
    "firm_and_expert": (
        queries.GROUPS_FIRM_AND_EXPERT,
        config.FIRM_AND_EXPERT_MIN_LAWSUITS,
    ),
}

MAX_CLAIM_IDS_PER_GROUP = 15  # a long list would fill the prompt of an agent


def find_shared_groups(driver, kind):
    """The biggest groups of claims that share a phone, an address, a clinic and attorney, or a law firm and expert."""
    query, min_claims = GROUP_QUERIES[kind]
    records, _, _ = driver.execute_query(
        query, min_claims=min_claims, limit=config.MAX_SHARED_GROUPS_SHOWN
    )
    group_count = records[0]["group_count"]
    if group_count == 0:
        return {
            "message": f"No group of {min_claims} or more claims shares the same {kind.replace('_', ' ')}."
        }

    groups = []
    for group in records[0]["groups"]:
        groups.append(
            {
                "shared_value": group["shared_value"],
                "claim_count": group["claim_count"],
                "claim_ids": group["claim_ids"][:MAX_CLAIM_IDS_PER_GROUP],
            }
        )
    notes = [
        "A group is a possible link that needs human review. It is not proof of fraud.",
        "A group counts only when its claims come from at least 2 different incidents.",
    ]
    if group_count > len(groups):
        notes.append(
            f"{group_count} groups were found. The biggest {len(groups)} are shown."
        )
    if kind in ("phone", "address"):
        notes.append(
            "Family members can share a phone or an address. That alone is not network evidence."
        )
    return {
        "facts": {
            "kind": kind,
            "min_claims_per_group": min_claims,
            "group_count": group_count,
            "groups": groups,
        },
        "notes": notes,
        "sources": [
            f"Graph groups of claims that share the same {kind.replace('_', ' ')}"
        ],
    }
