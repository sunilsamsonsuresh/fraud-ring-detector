"""Plain-code tool: which other claims is ONE claim linked to, and why. No LLM is called here.

This is where the graph pays off. One claim alone can look normal. Many claims that share a
phone, an address, a clinic and an attorney, or a law firm and an expert, can show a pattern.

The result has the same two shapes as src/tools/claim_tools.py.
A link is a possible link that needs human review. It is never proof (CLAUDE.md, rule 14).
"""

from src import config
from src.graph import queries
from src.tools.claim_tools import rows_from

MAX_LINKED_CLAIMS = 25  # a long list would fill the prompt of an agent

# One query for each kind of link. The loop below runs them one after the other.
LINK_QUERIES = [
    queries.LINKS_SHARED_PHONE,
    queries.LINKS_SHARED_ADDRESS,
    queries.LINKS_CLINIC_AND_ATTORNEY,
    queries.LINKS_FIRM_AND_EXPERT,
]


def find_direct_links(driver, claim_id):
    """All direct links of a claim as one flat list, not cut at a maximum.

    Each item: {"linked_claim_id", "kind", "shared_value"}. The scoring rules count these links.
    The claim ID must be checked before (src/tools/checks.py)."""
    links = []
    for query in LINK_QUERIES:
        links.extend(rows_from(driver, query, claim_id))
    return links


def find_copied_story(driver, claim_id):
    """Story chunks of this claim that are near-copies of chunks in claims of other incidents (best first).

    Each item: document_id, page_number, other_claim_id, other_document_id, other_page_number, score.
    The claim ID must be checked before (src/tools/checks.py)."""
    records, _, _ = driver.execute_query(
        queries.COPIED_STORY,
        claim_id=claim_id,
        document_types=config.STORY_DOCUMENT_TYPES,
        index_name=config.CHUNK_VECTOR_INDEX_NAME,
        candidate_count=config.COPY_CANDIDATES,
        min_score=config.SIMILARITY_THRESHOLD,
    )
    return [record.data() for record in records]


def claim_has_story_text(driver, claim_id):
    """True when the claim has at least one story chunk (fnol, complaint or demand letter)."""
    records, _, _ = driver.execute_query(
        queries.CLAIM_HAS_STORY_TEXT,
        claim_id=claim_id,
        document_types=config.STORY_DOCUMENT_TYPES,
    )
    return len(records) > 0


def find_cluster(driver, claim_id, max_hops):
    """The claims joined to this claim by direct links, up to max_hops links away. The claim itself is included.

    Hop 1 = the direct links of the claim. Hop 2 = the direct links of the hop 1 claims. And so on.
    Returns a sorted list of claim IDs. The claim ID must be checked before (src/tools/checks.py)."""
    found = {claim_id}
    frontier = [claim_id]  # the claims whose links we read in this round
    for _ in range(max_hops):
        next_frontier = []
        for frontier_claim_id in frontier:
            for link in find_direct_links(driver, frontier_claim_id):
                if link["linked_claim_id"] not in found:
                    found.add(link["linked_claim_id"])
                    next_frontier.append(link["linked_claim_id"])
        frontier = next_frontier
        if not frontier:
            break
    return sorted(found)


def get_claim_neighbourhood(driver, claim_id):
    """The claims that share something with this claim, with the reason for each link.

    Direct links only (one hop). Links inside the same incident are not counted."""
    if not rows_from(driver, queries.CLAIM_EXISTS, claim_id):
        return {"message": f"Claim {claim_id} was not found in the graph."}

    # One claim can be linked in several ways. Example: C-1209 shares a phone AND an address.
    # So we group the links by the linked claim.
    links_by_claim = {}
    for link in find_direct_links(driver, claim_id):
        links_by_claim.setdefault(link["linked_claim_id"], []).append(
            {"kind": link["kind"], "shared_value": link["shared_value"]}
        )

    linked_claims = [
        {"claim_id": other_id, "links": links_by_claim[other_id]}
        for other_id in sorted(links_by_claim)
    ]
    notes = [
        "Links inside the same incident are not counted.",
        "A link is a possible link that needs human review. It is not proof.",
        "Not checked here: other claims of the same claimant, and copied text.",
    ]
    if len(linked_claims) > MAX_LINKED_CLAIMS:
        notes.append(
            f"{len(linked_claims)} linked claims. The first {MAX_LINKED_CLAIMS} are shown."
        )
    facts = {
        "claim_id": claim_id,
        "linked_claim_count": len(linked_claims),
        "linked_claims": linked_claims[:MAX_LINKED_CLAIMS],
    }
    return {
        "facts": facts,
        "notes": notes,
        "sources": [
            f"Graph links of {claim_id}: phone, address, clinic and attorney, law firm and expert"
        ],
    }
