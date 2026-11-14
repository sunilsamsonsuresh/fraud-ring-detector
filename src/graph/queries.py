"""All Cypher queries of the new system, as named constants.

Rules:
1. A query lives here, as a constant with a clear name. No other file writes Cypher.
2. A value is always a parameter ($claim_id). We never build a query by joining text.
   So a bad value, even text like "MATCH (n) DETACH DELETE n", is only a value that matches nothing.
3. A new query is added when a new file needs it.

Cypher reads like a drawing of the graph: (claim:Claim) is a node with the label Claim,
-[:UNDER]-> is an edge, and {claim_id: $claim_id} is a filter on a property.
"""

# --- The claim and what hangs on it ---------------------------------------------------------

CLAIM_EXISTS = """
MATCH (claim:Claim {claim_id: $claim_id})
RETURN claim.claim_id AS claim_id
"""

# OPTIONAL MATCH: a claim without a policy or an incident still gives one row (with nulls).
CLAIM_AND_POLICY = """
MATCH (claim:Claim {claim_id: $claim_id})
OPTIONAL MATCH (claim)-[:UNDER]->(policy:Policy)
OPTIONAL MATCH (claim)-[:ARISES_FROM]->(incident:Incident)
RETURN claim.claim_id AS claim_id,
       claim.loss_date AS loss_date,
       claim.reported_date AS reported_date,
       claim.attorney_retained_date AS attorney_retained_date,
       claim.repair_estimate_amount AS repair_estimate_amount,
       incident.incident_id AS incident_id,
       policy.policy_id AS policy_id,
       policy.effective_date AS effective_date,
       policy.expiration_date AS expiration_date,
       policy.customer_since AS customer_since,
       policy.last_coverage_increase_date AS last_coverage_increase_date,
       policy.lapse_start AS lapse_start,
       policy.lapse_end AS lapse_end
"""

CLAIM_VISIT_DATES = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_TREATMENT]->(visit:Treatment)
RETURN visit.visit_date AS visit_date
ORDER BY visit_date, visit.treatment_id
"""

CLAIM_PAYMENTS = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_PAYMENT]->(payment:Payment)
RETURN payment.payment_id AS payment_id,
       payment.payment_date AS payment_date,
       payment.amount AS amount,
       payment.payment_type AS payment_type
ORDER BY payment_date, payment_id
"""

CLAIM_RESERVE_EVENTS = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_RESERVE_EVENT]->(event:ReserveEvent)
RETURN event.event_id AS event_id,
       event.event_date AS event_date,
       event.reserve_total AS reserve_total
ORDER BY event_date, event_id
"""

CLAIM_LAWSUITS = """
MATCH (:Claim {claim_id: $claim_id})-[:LED_TO]->(lawsuit:Lawsuit)
RETURN lawsuit.lawsuit_id AS lawsuit_id,
       lawsuit.filed_date AS filed_date,
       lawsuit.limitation_deadline AS limitation_deadline,
       lawsuit.settlement_date AS settlement_date
ORDER BY lawsuit_id
"""

# --- Links between claims (who shares something with this claim) ----------------------------
#
# Every query ignores links between claims of the SAME incident: those claims are one accident,
# so a shared phone or address there is not evidence of a network (CLAUDE.md, rule 20).
# A strong link is: the same phone, the same address, the same clinic AND the same attorney,
# or the same law firm AND the same expert. Each kind has its own query, with the same columns.
# Two MATCH clauses on purpose: a claimant with two claims has only one edge to the phone.

LINKS_SHARED_PHONE = """
MATCH (source:Claim {claim_id: $claim_id})<-[:FILED]-(:Claimant)-[:HAS_PHONE]->(phone:Phone)
MATCH (phone)<-[:HAS_PHONE]-(:Claimant)-[:FILED]->(linked:Claim)
WHERE linked <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT linked.claim_id AS linked_claim_id, "phone" AS kind, phone.number AS shared_value
ORDER BY linked_claim_id
"""

LINKS_SHARED_ADDRESS = """
MATCH (source:Claim {claim_id: $claim_id})<-[:FILED]-(:Claimant)-[:LIVES_AT]->(address:Address)
MATCH (address)<-[:LIVES_AT]-(:Claimant)-[:FILED]->(linked:Claim)
WHERE linked <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT linked.claim_id AS linked_claim_id, "address" AS kind,
       address.street + ", " + address.city AS shared_value
ORDER BY linked_claim_id
"""

LINKS_CLINIC_AND_ATTORNEY = """
MATCH (source:Claim {claim_id: $claim_id})-[:TREATED_BY]->(clinic:Provider)
MATCH (source)-[:REPRESENTED_BY]->(attorney:Attorney)
MATCH (clinic)<-[:TREATED_BY]-(linked:Claim)-[:REPRESENTED_BY]->(attorney)
WHERE linked <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT linked.claim_id AS linked_claim_id, "clinic_and_attorney" AS kind,
       clinic.name + " + " + attorney.name AS shared_value
ORDER BY linked_claim_id
"""

# The law firm and the expert are on the lawsuit, so we compare the lawsuits of both claims.
LINKS_FIRM_AND_EXPERT = """
MATCH (source:Claim {claim_id: $claim_id})-[:LED_TO]->(own:Lawsuit)-[:PLAINTIFF_COUNSEL]->(firm:LawFirm)
MATCH (own)-[:USES_EXPERT]->(expert:Expert)
MATCH (firm)<-[:PLAINTIFF_COUNSEL]-(other:Lawsuit)-[:USES_EXPERT]->(expert)
MATCH (other)<-[:LED_TO]-(linked:Claim)
WHERE linked <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT linked.claim_id AS linked_claim_id, "firm_and_expert" AS kind,
       firm.name + " + " + expert.name AS shared_value,
       own.filed_date AS source_filed_date, other.filed_date AS linked_filed_date
ORDER BY linked_claim_id
"""

# --- Other claims of the same claimant (the NL-2 rule) ---------------------------------------
# Same rule as the links: a second claim from the SAME incident is not a repeat claim.

REPEAT_CLAIMS_OF_CLAIMANT = """
MATCH (source:Claim {claim_id: $claim_id})<-[:FILED]-(person:Claimant)
MATCH (person)-[:FILED]->(other:Claim)
WHERE other <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(other) }
RETURN other.claim_id AS claim_id, other.loss_date AS loss_date
ORDER BY claim_id
"""

# --- Loss dates written in the PDFs (the AS-7 rule) ---------------------------------------------
# loss_date_in_pdf and its page were read from the PDF when the documents were loaded. Not every
# document states a loss date, so the date can be null. The page number is the evidence (CLAUDE.md, rule 6).

CLAIM_DOCUMENT_LOSS_DATES = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(document:Document)
RETURN document.document_id AS document_id,
       document.document_type AS document_type,
       document.loss_date_in_pdf AS loss_date_in_pdf,
       document.loss_date_page_number AS page_number
ORDER BY document_id
"""

# --- Findings read from the PDFs (the notes rules) ------------------------------------------
# A finding is one rating of one feature (for example injury_crash_fit = "Inconsistent"), with
# a confidence, a quote and the page where the quote is. severity_rank is the place of the rating
# in the list of allowed ratings: 0 = least suspicious. ORDER BY makes the result always the same.

CLAIM_FINDINGS = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_FINDING]->(finding:Finding)-[:FOUND_IN]->(document:Document)
RETURN finding.finding_id AS finding_id, finding.feature AS feature, finding.value AS value,
       finding.severity_rank AS severity_rank, finding.confidence AS confidence, finding.quote AS quote,
       finding.page_number AS page_number, finding.note_date AS note_date,
       document.document_id AS document_id, document.document_type AS document_type
ORDER BY finding_id
"""

# --- Claimants of the incident (the AS-6 rule) -----------------------------------------------
# Different people who filed a claim for the same incident. One person who filed twice counts once.
# A claim with no incident returns no row.

INCIDENT_CLAIMANT_COUNT = """
MATCH (:Claim {claim_id: $claim_id})-[:ARISES_FROM]->(incident:Incident)
MATCH (incident)<-[:ARISES_FROM]-(:Claim)<-[:FILED]-(person:Claimant)
RETURN incident.incident_id AS incident_id, count(DISTINCT person.claimant_id) AS claimants_in_incident
"""

# --- Copied story (the NL-4 rule) ---------------------------------------------------------------
# The vector index returns the chunks closest to each story chunk of this claim. Plain Cypher then keeps
# only chunks of the same document type, with a score at the threshold or above, from claims of OTHER
# incidents (a copy inside one incident is not network evidence, CLAUDE.md rule 20).
# The embeddings are already stored on the chunks, so no embedding model runs here.
# Parameters: $document_types, $index_name, $candidate_count, $min_score.

COPIED_STORY = """
MATCH (claim:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(own_document:Document)-[:HAS_CHUNK]->(own:Chunk)
WHERE own_document.document_type IN $document_types
CALL db.index.vector.queryNodes($index_name, $candidate_count, own.embedding) YIELD node AS other, score
WITH claim, own_document, own, other, score
WHERE score >= $min_score
MATCH (other_claim:Claim)-[:HAS_DOCUMENT]->(other_document:Document)-[:HAS_CHUNK]->(other)
WHERE other_claim <> claim AND other_document.document_type = own_document.document_type
  AND NOT EXISTS { MATCH (claim)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(other_claim) }
RETURN own_document.document_id AS document_id, own.page_number AS page_number,
       other_claim.claim_id AS other_claim_id, other_document.document_id AS other_document_id,
       other.page_number AS other_page_number, score
ORDER BY score DESC, document_id, other_document_id
"""

# NL-4 needs the claim's own story text. A claim with no story chunk returns no row: the rule is "not evaluated".
CLAIM_HAS_STORY_TEXT = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(document:Document)-[:HAS_CHUNK]->(:Chunk)
WHERE document.document_type IN $document_types
RETURN DISTINCT document.document_id AS document_id
ORDER BY document_id
"""


# --- Lookups by one value, and text search (used by src/tools/search_tools.py) ---------------------

# The claims of every claimant with this phone number. $phone_end is a whole number ("713-555-0142")
# or its last 7 digits ("555-0142"). ENDS WITH covers both.
CLAIMS_WITH_PHONE = """
MATCH (phone:Phone)<-[:HAS_PHONE]-(:Claimant)-[:FILED]->(claim:Claim)
WHERE phone.number ENDS WITH $phone_end
RETURN DISTINCT claim.claim_id AS claim_id, phone.number AS shared_value
ORDER BY claim_id
"""

# The claims linked to a clinic, repair shop, attorney or law firm with this name (no case difference).
# $exact = true: the whole name must match. false: the name only has to contain the text.
CLAIMS_LINKED_TO_NAME = """
MATCH (claim:Claim)-[link:TREATED_BY|REPAIRED_AT|REPRESENTED_BY]->(partner)
WHERE ($exact AND toLower(partner.name) = toLower($name)) OR (NOT $exact AND toLower(partner.name) CONTAINS toLower($name))
RETURN DISTINCT claim.claim_id AS claim_id, type(link) AS link_type, partner.name AS shared_value
UNION
MATCH (claim:Claim)-[:REPRESENTED_BY]->(:Attorney)-[:WORKS_AT]->(firm:LawFirm)
WHERE ($exact AND toLower(firm.name) = toLower($name)) OR (NOT $exact AND toLower(firm.name) CONTAINS toLower($name))
RETURN DISTINCT claim.claim_id AS claim_id, "LAW_FIRM" AS link_type, firm.name AS shared_value
"""

# The chunks of ONE claim, closest in meaning to the question first. $embedding is the question as 384 numbers.
# vector.similarity.cosine gives 1 for the same direction and 0 for no relation.
SEARCH_CHUNKS_OF_CLAIM = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(document:Document)-[:HAS_CHUNK]->(piece:Chunk)
WITH document, piece, vector.similarity.cosine(piece.embedding, $embedding) AS score
ORDER BY score DESC, piece.chunk_id
LIMIT $limit
RETURN document.document_id AS document_id, document.file_name AS file_name,
       piece.page_number AS page_number, piece.chunk_id AS chunk_id, piece.text AS text, score
"""


# --- Hybrid search over ALL documents (document search agent) ----------------------------------------
# Two ways to find chunks: by meaning (the vector index) and by words (the full-text index).
# Each query returns chunk IDs, best first. Plain code mixes the two lists (src/tools/search_tools.py).
SEARCH_CHUNKS_BY_MEANING = """
CALL db.index.vector.queryNodes($index_name, $candidate_count, $embedding) YIELD node, score
RETURN node.chunk_id AS chunk_id, score
"""

SEARCH_CHUNKS_BY_WORDS = """
CALL db.index.fulltext.queryNodes($text_index_name, $words, {limit: $candidate_count}) YIELD node, score
RETURN node.chunk_id AS chunk_id, score
"""

# Graph expansion: from each chunk to its document, claim, claimant, newest saved score, and the findings
# that were read on the same page. One row for each chunk. The rows come in any order.
EXPAND_CHUNKS = """
UNWIND $chunk_ids AS wanted_chunk_id
MATCH (claim:Claim)-[:HAS_DOCUMENT]->(document:Document)-[:HAS_CHUNK]->(piece:Chunk {chunk_id: wanted_chunk_id})
OPTIONAL MATCH (claimant:Claimant)-[:FILED]->(claim)
OPTIONAL MATCH (claim)-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
WITH claim, document, piece, claimant, snapshot ORDER BY snapshot.as_of_date DESC
WITH claim, document, piece, claimant, head(collect(snapshot)) AS latest
OPTIONAL MATCH (claim)-[:HAS_FINDING]->(finding:Finding)-[:FOUND_IN]->(document)
WHERE finding.page_number = piece.page_number
RETURN piece.chunk_id AS chunk_id, claim.claim_id AS claim_id, document.file_name AS file_name,
       piece.page_number AS page_number, piece.text AS text,
       claimant.first_name + " " + claimant.last_name AS claimant_name, latest.band AS band,
       collect(DISTINCT finding.feature + ": " + finding.value) AS findings_on_page
"""


# --- Groups of claims that share something, across ALL claims (questions with no claim ID) ----------
# Each query returns one row: the total number of groups, and the biggest $limit groups.
# A group counts only when its claims come from at least 2 different incidents (CLAUDE.md, rule 20),
# and (for a phone or an address) from at least 2 different claimants. $min_claims is the smallest group.

GROUPS_SHARED_PHONE = """
MATCH (phone:Phone)<-[:HAS_PHONE]-(claimant:Claimant)-[:FILED]->(claim:Claim)-[:ARISES_FROM]->(incident:Incident)
WITH phone.number AS shared_value, collect(DISTINCT claim.claim_id) AS claim_ids,
     count(DISTINCT claimant) AS claimant_count, count(DISTINCT incident) AS incident_count
WHERE claimant_count >= 2 AND incident_count >= 2 AND size(claim_ids) >= $min_claims
WITH shared_value, claim_ids ORDER BY size(claim_ids) DESC, shared_value
WITH collect({shared_value: shared_value, claim_count: size(claim_ids), claim_ids: claim_ids}) AS groups
RETURN size(groups) AS group_count, groups[0..$limit] AS groups
"""

GROUPS_SHARED_ADDRESS = """
MATCH (address:Address)<-[:LIVES_AT]-(claimant:Claimant)-[:FILED]->(claim:Claim)-[:ARISES_FROM]->(incident:Incident)
WITH address.street + ", " + address.city AS shared_value, collect(DISTINCT claim.claim_id) AS claim_ids,
     count(DISTINCT claimant) AS claimant_count, count(DISTINCT incident) AS incident_count
WHERE claimant_count >= 2 AND incident_count >= 2 AND size(claim_ids) >= $min_claims
WITH shared_value, claim_ids ORDER BY size(claim_ids) DESC, shared_value
WITH collect({shared_value: shared_value, claim_count: size(claim_ids), claim_ids: claim_ids}) AS groups
RETURN size(groups) AS group_count, groups[0..$limit] AS groups
"""

GROUPS_CLINIC_AND_ATTORNEY = """
MATCH (claim:Claim)-[:TREATED_BY]->(clinic:Provider)
MATCH (claim)-[:REPRESENTED_BY]->(attorney:Attorney)
MATCH (claim)-[:ARISES_FROM]->(incident:Incident)
WITH clinic.name + " + " + attorney.name AS shared_value, collect(DISTINCT claim.claim_id) AS claim_ids,
     count(DISTINCT incident) AS incident_count
WHERE incident_count >= 2 AND size(claim_ids) >= $min_claims
WITH shared_value, claim_ids ORDER BY size(claim_ids) DESC, shared_value
WITH collect({shared_value: shared_value, claim_count: size(claim_ids), claim_ids: claim_ids}) AS groups
RETURN size(groups) AS group_count, groups[0..$limit] AS groups
"""

GROUPS_FIRM_AND_EXPERT = """
MATCH (claim:Claim)-[:LED_TO]->(suit:Lawsuit)-[:PLAINTIFF_COUNSEL]->(firm:LawFirm)
MATCH (suit)-[:USES_EXPERT]->(expert:Expert)
MATCH (claim)-[:ARISES_FROM]->(incident:Incident)
WITH firm.name + " + " + expert.name AS shared_value, collect(DISTINCT claim.claim_id) AS claim_ids,
     count(DISTINCT incident) AS incident_count
WHERE incident_count >= 2 AND size(claim_ids) >= $min_claims
WITH shared_value, claim_ids ORDER BY size(claim_ids) DESC, shared_value
WITH collect({shared_value: shared_value, claim_count: size(claim_ids), claim_ids: claim_ids}) AS groups
RETURN size(groups) AS group_count, groups[0..$limit] AS groups
"""


# --- Saved scores of ALL claims (questions with no claim ID) ----------------------------------------
# A ScoreSnapshot is a score saved on one date. A claim has many (its score over time). We read the NEWEST of each
# claim. OPTIONAL MATCH keeps a claim that has no snapshot (its values are then null), so we can count those.
# collect() skips null, so head(collect(...)) is null for such a claim.
LATEST_SCORE_OF_EVERY_CLAIM = """
MATCH (claim:Claim)
OPTIONAL MATCH (claim)-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
WITH claim, snapshot ORDER BY snapshot.as_of_date DESC
WITH claim, head(collect(snapshot)) AS latest
RETURN claim.claim_id AS claim_id, latest.total_score AS total_score, latest.band AS band,
       latest.coverage_pct AS coverage_pct, toString(latest.as_of_date) AS as_of_date,
       latest.fired_rule_ids AS fired_rule_ids
ORDER BY claim_id
"""


# --- Entity context: everything around ONE person, business, phone or address (local search) -------
# Find the entity by a part of its name. Each row: kind (node label), entity_id, name.
ENTITIES_NAMED = """
MATCH (n:Claimant) WHERE toLower(n.first_name + " " + n.last_name) CONTAINS toLower($name)
RETURN "Claimant" AS kind, n.claimant_id AS entity_id, n.first_name + " " + n.last_name AS name
UNION
MATCH (n:Provider) WHERE toLower(n.name) CONTAINS toLower($name)
RETURN "Provider" AS kind, n.provider_id AS entity_id, n.name AS name
UNION
MATCH (n:Attorney) WHERE toLower(n.name) CONTAINS toLower($name)
RETURN "Attorney" AS kind, n.attorney_id AS entity_id, n.name AS name
UNION
MATCH (n:LawFirm) WHERE toLower(n.name) CONTAINS toLower($name)
RETURN "LawFirm" AS kind, n.law_firm_id AS entity_id, n.name AS name
UNION
MATCH (n:Expert) WHERE toLower(n.name) CONTAINS toLower($name)
RETURN "Expert" AS kind, n.expert_id AS entity_id, n.name AS name
UNION
MATCH (n:Address) WHERE toLower(n.street + ", " + n.city) CONTAINS toLower($name)
RETURN "Address" AS kind, n.address_id AS entity_id, n.street + ", " + n.city AS name
"""

# A phone: $phone_end is a whole number ("713-555-0142") or its last 7 digits ("555-0142").
ENTITIES_WITH_PHONE = """
MATCH (n:Phone) WHERE n.number ENDS WITH $phone_end
RETURN "Phone" AS kind, n.number AS entity_id, n.number AS name
"""

# The node itself. $kind is a label and $id_property its ID key, both from a fixed list in plain code.
# n[$id_property] reads a property whose name is a parameter, so no query text is ever joined.
ENTITY_DETAILS = """
MATCH (n) WHERE $kind IN labels(n) AND n[$id_property] = $entity_id
RETURN properties(n) AS details
"""

# The documents that mention the entity, with the page (from the document graph).
ENTITY_MENTIONS = """
MATCH (claim:Claim)-[:HAS_DOCUMENT]->(document:Document)-[mention:MENTIONS]->(n)
WHERE $kind IN labels(n) AND n[$id_property] = $entity_id
RETURN claim.claim_id AS claim_id, document.document_id AS document_id,
       document.document_type AS document_type, mention.page_number AS page_number
ORDER BY claim_id, document_id
"""

# The claims of the entity, with its role in each claim. One query for each kind.
CLAIMS_OF_CLAIMANT = """
MATCH (:Claimant {claimant_id: $entity_id})-[:FILED]->(claim:Claim)
RETURN claim.claim_id AS claim_id, "claimant" AS role
"""

CLAIMS_OF_PROVIDER = """
MATCH (claim:Claim)-[link:TREATED_BY|REPAIRED_AT]->(:Provider {provider_id: $entity_id})
RETURN claim.claim_id AS claim_id,
       CASE type(link) WHEN "TREATED_BY" THEN "treating clinic" ELSE "repair shop" END AS role
"""

CLAIMS_OF_ATTORNEY = """
MATCH (claim:Claim)-[:REPRESENTED_BY]->(:Attorney {attorney_id: $entity_id})
RETURN claim.claim_id AS claim_id, "attorney of the claimant" AS role
"""

CLAIMS_OF_LAW_FIRM = """
MATCH (claim:Claim)-[:REPRESENTED_BY]->(:Attorney)-[:WORKS_AT]->(:LawFirm {law_firm_id: $entity_id})
RETURN claim.claim_id AS claim_id, "law firm of the attorney" AS role
UNION
MATCH (claim:Claim)-[:LED_TO]->(:Lawsuit)-[:PLAINTIFF_COUNSEL]->(:LawFirm {law_firm_id: $entity_id})
RETURN claim.claim_id AS claim_id, "plaintiff counsel in the lawsuit" AS role
"""

CLAIMS_OF_EXPERT = """
MATCH (claim:Claim)-[:LED_TO]->(:Lawsuit)-[:USES_EXPERT]->(:Expert {expert_id: $entity_id})
RETURN claim.claim_id AS claim_id, "expert in the lawsuit" AS role
"""

CLAIMS_OF_PHONE = """
MATCH (:Phone {number: $entity_id})<-[:HAS_PHONE]-(:Claimant)-[:FILED]->(claim:Claim)
RETURN DISTINCT claim.claim_id AS claim_id, "phone of the claimant" AS role
"""

CLAIMS_OF_ADDRESS = """
MATCH (:Address {address_id: $entity_id})<-[:LIVES_AT]-(:Claimant)-[:FILED]->(claim:Claim)
RETURN DISTINCT claim.claim_id AS claim_id, "address of the claimant" AS role
"""

# The loss date and the newest saved score of each claim in $claim_ids.
CLAIMS_SUMMARY = """
UNWIND $claim_ids AS wanted_claim_id
MATCH (claim:Claim {claim_id: wanted_claim_id})
OPTIONAL MATCH (claim)-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
WITH claim, snapshot ORDER BY snapshot.as_of_date DESC
WITH claim, head(collect(snapshot)) AS latest
RETURN claim.claim_id AS claim_id, toString(claim.loss_date) AS loss_date,
       latest.total_score AS total_score, latest.band AS band
ORDER BY claim_id
"""


# --- The graph map: what is in the graph (pipeline, src/data_loading/write_graph_map.py) -------------
# A label or a property name cannot be a $parameter after ":" or ".", so we compare with labels(n) and
# read n[$property] instead. Each node has exactly one label.
GRAPH_MAP_LABELS = """
MATCH (n)
RETURN labels(n)[0] AS label, count(*) AS count
ORDER BY label
"""

GRAPH_MAP_NODE_PROPERTIES = """
MATCH (n) WHERE $label IN labels(n)
WITH n LIMIT 200
UNWIND keys(n) AS property
RETURN DISTINCT property ORDER BY property
"""

GRAPH_MAP_RELATIONSHIPS = """
MATCH (start)-[link]->(end)
RETURN labels(start)[0] AS from_label, type(link) AS type, labels(end)[0] AS to_label, count(*) AS count
ORDER BY type, from_label, to_label
"""

GRAPH_MAP_RELATIONSHIP_PROPERTIES = """
MATCH ()-[link]->() WHERE type(link) = $type
WITH link LIMIT 200
UNWIND keys(link) AS property
RETURN DISTINCT property ORDER BY property
"""

GRAPH_MAP_VALUES = """
MATCH (n) WHERE $label IN labels(n) AND n[$property] IS NOT NULL
RETURN DISTINCT n[$property] AS value
ORDER BY value LIMIT 25
"""


# --- Communities: groups of claims joined by strong links (global search) ----------------------------
# The pipeline writes them (src/data_loading/load_communities_into_graph.py, which also holds the two
# write queries: this file holds only queries that read). facts_json holds the facts
# that plain code found, as JSON text (a node property cannot hold a dict). report is the LLM report, or "".
ALL_CLAIM_IDS = """
MATCH (claim:Claim)
RETURN claim.claim_id AS claim_id
ORDER BY claim_id
"""

LIST_COMMUNITIES = """
MATCH (community:Community)
WITH community ORDER BY community.claim_count DESC, community.community_id
WITH collect(community) AS communities
RETURN size(communities) AS community_count,
       [community IN communities[0..$limit] | {community_id: community.community_id,
        facts_json: community.facts_json, report: community.report}] AS communities
"""

COMMUNITY_BY_ID = """
MATCH (community:Community {community_id: $community_id})
RETURN community.community_id AS community_id, community.facts_json AS facts_json, community.report AS report
"""

COMMUNITY_OF_CLAIM = """
MATCH (:Claim {claim_id: $claim_id})-[:IN_COMMUNITY]->(community:Community)
RETURN community.community_id AS community_id
"""
