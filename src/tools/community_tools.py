"""Plain-code tools of the global search agent: the communities (groups of linked claims). No LLM is called here.

list_communities:  all communities, the biggest first, each with what its claims share, bands and report.
get_community:     ONE community (by its ID, or by a claim in it), with all its facts and its report.

The pipeline finds the communities and saves them (src/data_loading/load_communities_into_graph.py).
The facts come from plain code. The report, when there is one, comes from the cheap LLM and was checked.
A community is a group of possible links that needs human review. It is never proof.
"""

import json

from src import config
from src.graph import queries

REPORT_PREVIEW_CHARACTERS = (
    400  # the list shows the start of each report; get_community shows all of it
)
NOTES = [
    (
        "A community is a group of claims joined by strong links: the same phone, address, clinic and "
        "attorney, or law firm and expert. Links inside one incident are not counted."
    ),
    "A community is a group of possible links that needs human review. It is not proof of fraud.",
]


def report_or_note(report):
    if report:
        return report
    return "No report was written yet. Use the facts."


def list_communities(driver):
    """The biggest communities (at most MAX_COMMUNITIES_SHOWN), each with its main facts and its report."""
    records, _, _ = driver.execute_query(
        queries.LIST_COMMUNITIES, limit=config.MAX_COMMUNITIES_SHOWN
    )
    community_count = records[0]["community_count"]
    if community_count == 0:
        return {
            "message": "The graph has no communities. "
            "Run: python -m src.data_loading.load_communities_into_graph"
        }
    communities = []
    for community in records[0]["communities"]:
        facts = json.loads(community["facts_json"])
        communities.append(
            {
                "community_id": facts["community_id"],
                "claim_count": facts["claim_count"],
                "shared": facts["shared"][:3],
                "band_counts": facts["band_counts"],
                "report": report_or_note(community["report"])[
                    :REPORT_PREVIEW_CHARACTERS
                ],
            }
        )
    notes = list(NOTES)
    if community_count > len(communities):
        notes.append(
            f"{community_count} communities exist. The biggest {len(communities)} are shown."
        )
    return {
        "facts": {"community_count": community_count, "communities": communities},
        "notes": notes,
        "sources": ["Communities of linked claims (graph)"],
    }


def get_community(driver, community_or_claim):
    """ONE community with all its facts and its report. community_or_claim comes from check_community_or_claim
    (src/tools/checks.py): ("community", "COM-01"), or ("claim", "C-1088") for the community of that claim."""
    kind, value = community_or_claim
    community_id = value
    if kind == "claim":
        records, _, _ = driver.execute_query(queries.COMMUNITY_OF_CLAIM, claim_id=value)
        if not records:
            return {
                "message": f"Claim {value} is in no community: it has strong links to fewer than "
                f"{config.COMMUNITY_MIN_CLAIMS - 1} other claims, or the claim does not exist."
            }
        community_id = records[0]["community_id"]
    records, _, _ = driver.execute_query(
        queries.COMMUNITY_BY_ID, community_id=community_id
    )
    if not records:
        return {"message": f"Community {community_id} was not found."}
    facts = json.loads(records[0]["facts_json"])
    facts["report"] = report_or_note(records[0]["report"])
    return {
        "facts": facts,
        "notes": list(NOTES),
        "sources": [f"Community {community_id} of linked claims (graph)"],
    }
