"""Plain-code tool for local search: everything around ONE person, business, phone or address. No LLM.

Example: "David Richardson" -> the attorney node -> his claims (and his role in each), their saved scores,
and the documents that mention him (with page). This is "local search" in GraphRAG: start at one entity
and read its neighbourhood in the domain graph AND in the document graph.

Order of work:
1. Find the entity: a phone number, or a part of a name or street. Never guess (CLAUDE.md, rule 10):
   no match gives a message, several matches give a list to pick from.
2. Read its details, its claims, their scores, and the documents that mention it.
The value is checked before (src/tools/checks.py) and goes into named queries as a parameter.
"""

from src.graph import queries
from src.tools.checks import check_phone

# kind (node label) -> (its ID property, the query for its claims). This is the fixed list of kinds.
ENTITY_KINDS = {
    "Claimant": ("claimant_id", queries.CLAIMS_OF_CLAIMANT),
    "Provider": ("provider_id", queries.CLAIMS_OF_PROVIDER),
    "Attorney": ("attorney_id", queries.CLAIMS_OF_ATTORNEY),
    "LawFirm": ("law_firm_id", queries.CLAIMS_OF_LAW_FIRM),
    "Expert": ("expert_id", queries.CLAIMS_OF_EXPERT),
    "Phone": ("number", queries.CLAIMS_OF_PHONE),
    "Address": ("address_id", queries.CLAIMS_OF_ADDRESS),
}
MAX_CLAIMS_SHOWN = 25  # long lists would fill the prompt of an agent
MAX_MENTIONS_SHOWN = 15


def run_query(driver, query, **parameters):
    records, _, _ = driver.execute_query(query, **parameters)
    return [record.data() for record in records]


def find_entity(driver, text):
    """Return (the entity row, None), or (None, a message for the person)."""
    phone, problem = check_phone(text)
    if problem is None:
        rows = run_query(driver, queries.ENTITIES_WITH_PHONE, phone_end=phone)
    else:
        rows = run_query(driver, queries.ENTITIES_NAMED, name=text)
    if not rows:
        return None, (
            f"Nothing named '{text}' was found: no person, clinic, repair shop, attorney, "
            "law firm, expert, phone or address."
        )
    exact_matches = [row for row in rows if row["name"].lower() == text.lower()]
    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(rows) == 1:
        return rows[0], None
    choices = sorted({f"{row['name']} ({row['kind']})" for row in rows})
    return (
        None,
        f"Several matches for '{text}': {', '.join(choices[:10])}. Which one do you mean?",
    )


def get_entity_context(driver, text):
    """The entity, its claims (with its role and their saved scores), and the documents that mention it."""
    entity, problem = find_entity(driver, text)
    if problem is not None:
        return {"message": problem}
    kind, entity_id = entity["kind"], entity["entity_id"]
    id_property, claims_query = ENTITY_KINDS[kind]
    where = {"kind": kind, "id_property": id_property, "entity_id": entity_id}

    details = run_query(driver, queries.ENTITY_DETAILS, **where)[0]["details"]
    roles_by_claim = {}
    for row in run_query(driver, claims_query, entity_id=entity_id):
        roles_by_claim.setdefault(row["claim_id"], []).append(row["role"])
    claims = []
    for row in run_query(
        driver, queries.CLAIMS_SUMMARY, claim_ids=sorted(roles_by_claim)
    ):
        claims.append(dict(row, roles=roles_by_claim[row["claim_id"]]))
    # Highest saved score first, so a cut list still shows the claims that matter most.
    claims.sort(key=lambda claim: (-(claim["total_score"] or 0), claim["claim_id"]))
    band_counts = {}
    for claim in claims:
        band_counts[claim["band"]] = band_counts.get(claim["band"], 0) + 1
    mentions = run_query(driver, queries.ENTITY_MENTIONS, **where)

    notes = [
        "Scores are the newest saved scores. A score is a pointer for a reviewer, not a finding of fraud.",
        "A shared person or business is a possible link that needs human review. It is not proof.",
    ]
    if len(claims) > MAX_CLAIMS_SHOWN:
        notes.append(
            f"{len(claims)} claims. The {MAX_CLAIMS_SHOWN} with the highest scores are shown."
        )
    if len(mentions) > MAX_MENTIONS_SHOWN:
        notes.append(
            f"{len(mentions)} document mentions. The first {MAX_MENTIONS_SHOWN} are shown."
        )
    facts = {
        "entity": {
            "kind": kind,
            "name": entity["name"],
            "entity_id": entity_id,
            "details": details,
        },
        "claim_count": len(claims),
        "claims_by_band": band_counts,
        "claims": claims[:MAX_CLAIMS_SHOWN],
        "documents_mentioning_count": len(mentions),
        "documents_mentioning": mentions[:MAX_MENTIONS_SHOWN],
    }
    sources = [f"Graph neighbourhood of {kind} '{entity['name']}'"]
    for mention in mentions[:MAX_MENTIONS_SHOWN]:
        sources.append(f"{mention['document_id']}, page {mention['page_number']}")
    return {"facts": facts, "notes": notes, "sources": sources}
