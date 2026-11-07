"""The fixed list of graph searches, and the plain code that runs them (PLAN.md, Step 5).

The Graph Investigator may only name templates from ALLOWED_TEMPLATE_NAMES.
Every function here checks the name (and the hop count) before it runs anything.
The claim IDs always come from our own code, never from the LLM.
"""

from src.graph import queries

# name -> (Cypher query, description shown to the LLM)
LINK_TEMPLATES = {
    "claims_sharing_phone": (queries.CLAIMS_SHARING_PHONE,
                             "Other claims whose claimant has the same phone number."),
    "claims_sharing_address": (queries.CLAIMS_SHARING_ADDRESS,
                               "Other claims whose claimant lives at the same address."),
    "claims_sharing_repair_shop": (queries.CLAIMS_SHARING_REPAIR_SHOP,
                                   "Other claims repaired at the same repair shop."),
    "claims_sharing_clinic": (queries.CLAIMS_SHARING_CLINIC,
                              "Other claims treated at the same clinic or doctor."),
    "claims_sharing_law_firm": (queries.CLAIMS_SHARING_LAW_FIRM,
                                "Other claims represented by an attorney of the same law firm."),
    "claims_sharing_expert": (queries.CLAIMS_SHARING_EXPERT,
                              "Other claims whose lawsuit uses the same expert witness."),
}

EXPAND_TEMPLATE_NAME = "expand_linked_claims"
EXPAND_DESCRIPTION = ("Runs all six searches above, then runs them again from every claim found, "
                      "for 1 to 3 rounds ('hops'). Finds claims linked through other claims. "
                      "More hops find more claims, but also more innocent ones.")
MIN_HOPS = 1
MAX_HOPS = 3

ALLOWED_TEMPLATE_NAMES = list(LINK_TEMPLATES) + [EXPAND_TEMPLATE_NAME]


def run_link_template(driver, template_name, claim_ids):
    """Run one "claims sharing" template. Return a list of link dicts."""
    if template_name not in LINK_TEMPLATES:
        raise ValueError(f"'{template_name}' is not an allowed template.")
    query, _ = LINK_TEMPLATES[template_name]
    records, _, _ = driver.execute_query(query, claim_ids=list(claim_ids))
    links = []
    for record in records:
        links.append({
            "template": template_name,
            "source_claim_id": record["source_claim_id"],
            "linked_claim_id": record["linked_claim_id"],
            "shared_value": record["shared_value"],
        })
    return links


def check_hops(hops):
    # bool is a kind of int in Python (True == 1), so reject it on purpose.
    if isinstance(hops, bool) or not isinstance(hops, int) or not MIN_HOPS <= hops <= MAX_HOPS:
        raise ValueError(f"hops must be a whole number from {MIN_HOPS} to {MAX_HOPS}, not {hops!r}.")


def expand_linked_claims(driver, start_claim_id, hops):
    """Find claims up to `hops` links away. Each link dict also gets its "hop" number.

    Hop 1: claims that share something with the start claim.
    Hop 2: claims that share something with a hop 1 claim. And so on.
    """
    check_hops(hops)
    hop_of_claim = {start_claim_id: 0}
    claims_to_search_from = [start_claim_id]
    all_links = []
    for hop in range(1, hops + 1):
        claims_found_this_hop = []
        for template_name in LINK_TEMPLATES:
            for link in run_link_template(driver, template_name, claims_to_search_from):
                linked_claim_id = link["linked_claim_id"]
                if linked_claim_id in hop_of_claim and hop_of_claim[linked_claim_id] < hop:
                    continue   # already found closer to the start claim; not new information
                if linked_claim_id not in hop_of_claim:
                    hop_of_claim[linked_claim_id] = hop
                    claims_found_this_hop.append(linked_claim_id)
                link["hop"] = hop
                all_links.append(link)
        if not claims_found_this_hop:
            break
        claims_to_search_from = claims_found_this_hop
    return all_links
