"""The network facts of one claim: plain code runs the fixed NL templates (PLAN-v2.md A7, V8).

Only the templates in NL_TEMPLATES run here, always with values as parameters. Every template
ignores links inside one incident (CLAUDE.md, rule 20). The NL rules (src/scoring/rules.py)
then decide from these facts.

The cluster search (NL-6) follows strong links hop by hop, like the v1 expansion:
  hop 1: the claims strongly linked to this claim,
  hop 2: the claims strongly linked to a hop 1 claim, and so on up to CLUSTER_MAX_HOPS.
It keeps every link it saw, with the reported date of each claim, so V9 can rebuild the
cluster as it was on an earlier date (only claims reported by then).
"""

from src import config
from src.graph import queries
from src.graph.schema import CHUNK_VECTOR_INDEX_NAME

# name -> (query, what it finds). The strong-link templates take a list of claim IDs.
STRONG_LINK_TEMPLATES = {
    "nl_links_shared_phone": (queries.NL_LINKS_SHARED_PHONE,
                              "Claims in other incidents whose claimant has the same phone number."),
    "nl_links_shared_address": (queries.NL_LINKS_SHARED_ADDRESS,
                                "Claims in other incidents whose claimant lives at the same address."),
    "nl_links_clinic_and_attorney": (queries.NL_LINKS_CLINIC_AND_ATTORNEY,
                                     "Claims in other incidents with the same clinic AND the same attorney."),
    "nl_links_firm_and_expert": (queries.NL_LINKS_FIRM_AND_EXPERT,
                                 "Claims in other incidents whose lawsuit has the same law firm AND expert."),
}
NL_TEMPLATES = dict(STRONG_LINK_TEMPLATES)
NL_TEMPLATES["nl_repeat_claims"] = (queries.NL_REPEAT_CLAIMS, "Other claims of the same claimant.")
NL_TEMPLATES["nl_copied_story"] = (queries.NL_COPIED_STORY,
                                   "Near-copies of this claim's story text in claims of other incidents.")

# How many closest chunks the vector index returns for each story chunk, before the filters.
COPY_CANDIDATES = 100


def native(value):
    """A Neo4j date becomes a Python date. Other values stay as they are."""
    if hasattr(value, "to_native"):
        return value.to_native()
    return value


def rows_of(records):
    rows = []
    for record in records:
        rows.append({key: native(value) for key, value in record.data().items()})
    return rows


def find_strong_links(driver, claim_ids):
    """All strong links from these claims (all four kinds), as a list of dicts."""
    links = []
    for query, _ in STRONG_LINK_TEMPLATES.values():
        records, _, _ = driver.execute_query(query, claim_ids=list(claim_ids))
        links.extend(rows_of(records))
    return links


def collect_cluster_links(driver, claim_id, max_hops):
    """Every strong link found while walking max_hops hops out from the claim."""
    seen = {claim_id}
    frontier = [claim_id]
    all_links = []
    for _ in range(max_hops):
        if not frontier:
            break
        links = find_strong_links(driver, frontier)
        all_links.extend(links)
        next_frontier = []
        for link in links:
            if link["linked_claim_id"] not in seen:
                seen.add(link["linked_claim_id"])
                next_frontier.append(link["linked_claim_id"])
        frontier = sorted(next_frontier)
    return all_links


def claims_within_hops(links, start_claim_id, max_hops, allowed_claim_ids=None):
    """The claims reachable from the start claim in max_hops strong links or fewer (start included).
    allowed_claim_ids: if given, the walk may only pass through these claims (V9: claims reported by a date)."""
    neighbours = {}
    for link in links:
        neighbours.setdefault(link["source_claim_id"], set()).add(link["linked_claim_id"])
        neighbours.setdefault(link["linked_claim_id"], set()).add(link["source_claim_id"])
    reached = {start_claim_id}
    frontier = [start_claim_id]
    for _ in range(max_hops):
        next_frontier = []
        for claim_id in frontier:
            for neighbour in sorted(neighbours.get(claim_id, set())):
                if neighbour in reached:
                    continue
                if allowed_claim_ids is not None and neighbour not in allowed_claim_ids:
                    continue
                reached.add(neighbour)
                next_frontier.append(neighbour)
        frontier = next_frontier
    return reached


def find_copied_story(driver, claim_id):
    """Near-copies of this claim's story chunks in claims of other incidents (best first)."""
    records, _, _ = driver.execute_query(
        queries.NL_COPIED_STORY, claim_id=claim_id, document_types=config.STORY_DOCUMENT_TYPES,
        index_name=CHUNK_VECTOR_INDEX_NAME, candidate_count=COPY_CANDIDATES, min_score=config.SIMILARITY_THRESHOLD)
    return rows_of(records)


def read_network_facts(driver, claim_id):
    """The raw network facts of one claim. Dates are Python dates."""
    cluster_links = collect_cluster_links(driver, claim_id, config.CLUSTER_MAX_HOPS)
    reported_dates = {}
    for link in cluster_links:
        reported_dates[link["linked_claim_id"]] = link["linked_reported_date"]

    records, _, _ = driver.execute_query(queries.NL_REPEAT_CLAIMS, claim_id=claim_id)
    repeat_claims = rows_of(records)

    copied_story = find_copied_story(driver, claim_id)

    records, _, _ = driver.execute_query(queries.STORY_DOCUMENT_TYPES_OF_CLAIM, claim_id=claim_id,
                                         document_types=config.STORY_DOCUMENT_TYPES)
    story_document_types = [record["document_type"] for record in records]

    return {
        "direct_links": [link for link in cluster_links if link["source_claim_id"] == claim_id],
        "cluster_links": cluster_links,
        "reported_dates": reported_dates,
        "repeat_claims": repeat_claims,
        "copied_story": copied_story,
        "story_document_types": story_document_types,
    }
