"""All Cypher queries of the project, as named constants (CLAUDE.md, rule 5.2).

Values always come in as parameters ($rows, $pairs). No query is built by
joining strings. Labels and edge types cannot be parameters in Cypher, so
each node type and each edge type has its own query.

Part 1 (Step 4): loading the CSV tables.
Part 2 (Step 5): the fixed investigation templates.
Part 3 (Step 6): documents and the entities they mention.
Part 4 (Step 7): chunks and text search.
Part 5 (Step 8): lawsuits.
Part 6 (Step 9): Challenger facts and saving the result.
"""

# --- Part 1: loading -------------------------------------------------------
#
# UNWIND $rows AS row  -> repeat the rest of the query once for each row in the list.
# MERGE                -> find the node with this ID, or create it. Running twice is safe.
# SET                  -> write the other properties. date(), toFloat() and toInteger()
#                         turn CSV text into real types. toFloat("") gives null,
#                         and a null property is simply not stored.

LOAD_ADDRESSES = """
UNWIND $rows AS row
MERGE (address:Address {address_id: row.address_id})
SET address.street = row.street, address.city = row.city,
    address.state = row.state, address.zip_code = row.zip_code
"""

LOAD_PHONES = """
UNWIND $rows AS row
MERGE (:Phone {number: row.phone_number})
"""

LOAD_CLAIMANTS = """
UNWIND $rows AS row
MERGE (claimant:Claimant {claimant_id: row.claimant_id})
SET claimant.first_name = row.first_name, claimant.last_name = row.last_name,
    claimant.date_of_birth = date(row.date_of_birth)
"""

LOAD_POLICIES = """
UNWIND $rows AS row
MERGE (policy:Policy {policy_id: row.policy_id})
SET policy.effective_date = date(row.effective_date),
    policy.expiration_date = date(row.expiration_date),
    policy.bodily_injury_limit = toInteger(row.bodily_injury_limit)
"""

LOAD_VEHICLES = """
UNWIND $rows AS row
MERGE (vehicle:Vehicle {vehicle_id: row.vehicle_id})
SET vehicle.vin = row.vin, vehicle.year = toInteger(row.year), vehicle.make = row.make,
    vehicle.model = row.model, vehicle.license_plate = row.license_plate
"""

LOAD_CLAIMS = """
UNWIND $rows AS row
MERGE (claim:Claim {claim_id: row.claim_id})
SET claim.loss_date = date(row.loss_date), claim.reported_date = date(row.reported_date),
    claim.loss_city = row.loss_city, claim.accident_type = row.accident_type,
    claim.injury_type = row.injury_type, claim.status = row.status,
    claim.repair_estimate_amount = toFloat(row.repair_estimate_amount),
    claim.treatment_visits = toInteger(row.treatment_visits),
    claim.medical_bill_amount = toFloat(row.medical_bill_amount)
"""

LOAD_PROVIDERS = """
UNWIND $rows AS row
MERGE (provider:Provider {provider_id: row.provider_id})
SET provider.name = row.name, provider.type = row.type, provider.street = row.street,
    provider.city = row.city, provider.state = row.state, provider.phone_number = row.phone_number
"""

LOAD_ATTORNEYS = """
UNWIND $rows AS row
MERGE (attorney:Attorney {attorney_id: row.attorney_id})
SET attorney.name = row.name
"""

LOAD_LAW_FIRMS = """
UNWIND $rows AS row
MERGE (law_firm:LawFirm {law_firm_id: row.law_firm_id})
SET law_firm.name = row.name, law_firm.city = row.city,
    law_firm.state = row.state, law_firm.phone_number = row.phone_number
"""

LOAD_LAWSUITS = """
UNWIND $rows AS row
MERGE (lawsuit:Lawsuit {lawsuit_id: row.lawsuit_id})
SET lawsuit.filed_date = date(row.filed_date),
    lawsuit.limitation_deadline = date(row.limitation_deadline),
    lawsuit.demand_amount = toFloat(row.demand_amount), lawsuit.status = row.status
"""

# A5 has no Settlement node, so a settlement is stored on its Lawsuit.
LOAD_SETTLEMENTS_ONTO_LAWSUITS = """
UNWIND $rows AS row
MATCH (lawsuit:Lawsuit {lawsuit_id: row.lawsuit_id})
SET lawsuit.settlement_id = row.settlement_id,
    lawsuit.settlement_date = date(row.settlement_date),
    lawsuit.settlement_amount = toFloat(row.settlement_amount)
"""

LOAD_COURTS = """
UNWIND $rows AS row
MERGE (court:Court {court_id: row.court_id})
SET court.name = row.name, court.county = row.county, court.state = row.state
"""

LOAD_EXPERTS = """
UNWIND $rows AS row
MERGE (expert:Expert {expert_id: row.expert_id})
SET expert.name = row.name, expert.specialty = row.specialty
"""

LOAD_PAYMENTS = """
UNWIND $rows AS row
MERGE (payment:Payment {payment_id: row.payment_id})
SET payment.payment_date = date(row.payment_date), payment.amount = toFloat(row.amount),
    payment.payment_type = row.payment_type, payment.payee_name = row.payee_name
"""

# Edge queries. Each item in $pairs is {from_id: ..., to_id: ...}.
# MATCH (not MERGE) finds both nodes: a missing node means no edge, never a fake empty node.

LINK_CLAIMANT_FILED_CLAIM = """
UNWIND $pairs AS pair
MATCH (claimant:Claimant {claimant_id: pair.from_id}) MATCH (claim:Claim {claim_id: pair.to_id})
MERGE (claimant)-[:FILED]->(claim)
"""

LINK_CLAIM_UNDER_POLICY = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (policy:Policy {policy_id: pair.to_id})
MERGE (claim)-[:UNDER]->(policy)
"""

LINK_CLAIM_INVOLVES_VEHICLE = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (vehicle:Vehicle {vehicle_id: pair.to_id})
MERGE (claim)-[:INVOLVES]->(vehicle)
"""

LINK_CLAIMANT_LIVES_AT_ADDRESS = """
UNWIND $pairs AS pair
MATCH (claimant:Claimant {claimant_id: pair.from_id}) MATCH (address:Address {address_id: pair.to_id})
MERGE (claimant)-[:LIVES_AT]->(address)
"""

LINK_CLAIMANT_HAS_PHONE = """
UNWIND $pairs AS pair
MATCH (claimant:Claimant {claimant_id: pair.from_id}) MATCH (phone:Phone {number: pair.to_id})
MERGE (claimant)-[:HAS_PHONE]->(phone)
"""

LINK_CLAIM_REPAIRED_AT_PROVIDER = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (shop:Provider {provider_id: pair.to_id})
MERGE (claim)-[:REPAIRED_AT]->(shop)
"""

LINK_CLAIM_TREATED_BY_PROVIDER = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (clinic:Provider {provider_id: pair.to_id})
MERGE (claim)-[:TREATED_BY]->(clinic)
"""

LINK_CLAIM_REPRESENTED_BY_ATTORNEY = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (attorney:Attorney {attorney_id: pair.to_id})
MERGE (claim)-[:REPRESENTED_BY]->(attorney)
"""

LINK_ATTORNEY_WORKS_AT_LAW_FIRM = """
UNWIND $pairs AS pair
MATCH (attorney:Attorney {attorney_id: pair.from_id}) MATCH (law_firm:LawFirm {law_firm_id: pair.to_id})
MERGE (attorney)-[:WORKS_AT]->(law_firm)
"""

LINK_CLAIM_LED_TO_LAWSUIT = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (lawsuit:Lawsuit {lawsuit_id: pair.to_id})
MERGE (claim)-[:LED_TO]->(lawsuit)
"""

LINK_LAWSUIT_FILED_IN_COURT = """
UNWIND $pairs AS pair
MATCH (lawsuit:Lawsuit {lawsuit_id: pair.from_id}) MATCH (court:Court {court_id: pair.to_id})
MERGE (lawsuit)-[:FILED_IN]->(court)
"""

LINK_LAWSUIT_PLAINTIFF_COUNSEL = """
UNWIND $pairs AS pair
MATCH (lawsuit:Lawsuit {lawsuit_id: pair.from_id}) MATCH (law_firm:LawFirm {law_firm_id: pair.to_id})
MERGE (lawsuit)-[:PLAINTIFF_COUNSEL]->(law_firm)
"""

LINK_LAWSUIT_USES_EXPERT = """
UNWIND $pairs AS pair
MATCH (lawsuit:Lawsuit {lawsuit_id: pair.from_id}) MATCH (expert:Expert {expert_id: pair.to_id})
MERGE (lawsuit)-[:USES_EXPERT]->(expert)
"""

LINK_CLAIM_HAS_PAYMENT = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (payment:Payment {payment_id: pair.to_id})
MERGE (claim)-[:HAS_PAYMENT]->(payment)
"""

# Counts, used to check a load. labels(n)[0] is the node's first (and only) label.
COUNT_NODES_BY_LABEL = """
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count
"""

COUNT_EDGES_BY_TYPE = """
MATCH ()-[edge]->() RETURN type(edge) AS edge_type, count(*) AS count
"""


# --- Part 2: investigation templates (Step 5) -------------------------------
#
# The Graph Investigator can run ONLY these. Each "claims sharing" template takes
# a list of claim IDs ($claim_ids) and returns one row per link:
#   source_claim_id  - a claim from the list
#   linked_claim_id  - another claim that shares something with it
#   shared_value     - the shared thing, in words (for the report)
# A list (not one ID) lets the same template serve the 1 to 3 hop expansion.
# ORDER BY makes the result order the same on every run.
# Two MATCH clauses on purpose: inside ONE pattern, Cypher never walks the same edge
# twice. Two claims with the same attorney share one WORKS_AT edge, so a single
# pattern through the firm would silently drop them.

CLAIM_PROFILE = """
MATCH (claim:Claim {claim_id: $claim_id})
RETURN claim.claim_id AS claim_id, claim.accident_type AS accident_type,
       claim.injury_type AS injury_type,
       EXISTS { (claim)-[:REPAIRED_AT]->() } AS has_repair_shop,
       EXISTS { (claim)-[:TREATED_BY]->() } AS has_clinic,
       EXISTS { (claim)-[:REPRESENTED_BY]->() } AS has_attorney,
       EXISTS { (claim)-[:LED_TO]->(:Lawsuit)-[:USES_EXPERT]->() } AS has_expert
"""

CLAIMS_SHARING_PHONE = """
MATCH (source:Claim)<-[:FILED]-(:Claimant)-[:HAS_PHONE]->(phone:Phone)
MATCH (phone)<-[:HAS_PHONE]-(:Claimant)-[:FILED]->(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
RETURN source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       phone.number AS shared_value
ORDER BY source_claim_id, linked_claim_id
"""

CLAIMS_SHARING_ADDRESS = """
MATCH (source:Claim)<-[:FILED]-(:Claimant)-[:LIVES_AT]->(address:Address)
MATCH (address)<-[:LIVES_AT]-(:Claimant)-[:FILED]->(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
RETURN source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       address.street + ", " + address.city AS shared_value
ORDER BY source_claim_id, linked_claim_id
"""

CLAIMS_SHARING_REPAIR_SHOP = """
MATCH (source:Claim)-[:REPAIRED_AT]->(shop:Provider)
MATCH (shop)<-[:REPAIRED_AT]-(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
RETURN source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       shop.name AS shared_value
ORDER BY source_claim_id, linked_claim_id
"""

CLAIMS_SHARING_CLINIC = """
MATCH (source:Claim)-[:TREATED_BY]->(clinic:Provider)
MATCH (clinic)<-[:TREATED_BY]-(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
RETURN source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       clinic.name AS shared_value
ORDER BY source_claim_id, linked_claim_id
"""

# Two claims can have different attorneys at the same firm, so we go through the firm.
CLAIMS_SHARING_LAW_FIRM = """
MATCH (source:Claim)-[:REPRESENTED_BY]->(:Attorney)-[:WORKS_AT]->(firm:LawFirm)
MATCH (firm)<-[:WORKS_AT]-(:Attorney)<-[:REPRESENTED_BY]-(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
RETURN source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       firm.name AS shared_value
ORDER BY source_claim_id, linked_claim_id
"""

CLAIMS_SHARING_EXPERT = """
MATCH (source:Claim)-[:LED_TO]->(:Lawsuit)-[:USES_EXPERT]->(expert:Expert)
MATCH (expert)<-[:USES_EXPERT]-(:Lawsuit)<-[:LED_TO]-(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
RETURN source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       expert.name AS shared_value
ORDER BY source_claim_id, linked_claim_id
"""


# --- Part 3: documents (Step 6) ---------------------------------------------
#
# elementId(node) is Neo4j's own internal ID for a node. The matching code reads it
# once, and SAVE_MENTIONS uses it to find the node again. Labels cannot be
# parameters, so this lets ONE query link a document to any kind of node.

CLAIMANTS_FOR_MATCHING = """
MATCH (claimant:Claimant)
OPTIONAL MATCH (claimant)-[:HAS_PHONE]->(phone:Phone)
RETURN elementId(claimant) AS element_id, claimant.claimant_id AS node_id,
       claimant.first_name + " " + claimant.last_name AS name,
       claimant.date_of_birth AS date_of_birth, phone.number AS phone_number
"""

NODES_FOR_MATCHING = """
MATCH (node)
WHERE node:Phone OR node:Address OR node:Provider OR node:Attorney OR node:LawFirm
   OR node:Expert OR node:Court OR node:Vehicle OR node:Policy
RETURN elementId(node) AS element_id, labels(node)[0] AS label, properties(node) AS properties
"""

CLAIM_FACTS_FOR_CONFLICTS = """
MATCH (claimant:Claimant)-[:FILED]->(claim:Claim {claim_id: $claim_id})
OPTIONAL MATCH (claimant)-[:HAS_PHONE]->(phone:Phone)
RETURN claimant.claimant_id AS claimant_id,
       claimant.first_name + " " + claimant.last_name AS claimant_name,
       claim.loss_date AS loss_date, claimant.date_of_birth AS date_of_birth,
       phone.number AS phone, claim.repair_estimate_amount AS repair_estimate_total,
       claim.medical_bill_amount AS medical_bill_total
"""

SAVE_DOCUMENT = """
MATCH (claim:Claim {claim_id: $claim_id})
MERGE (document:Document {document_id: $document_id})
SET document.document_type = $document_type, document.file_name = $file_name,
    document.page_count = $page_count
MERGE (claim)-[:HAS_DOCUMENT]->(document)
"""

# One MENTIONS edge per (document, page, node). page_number is part of the MERGE key,
# so a name on page 1 and page 2 gives two edges, and a rerun gives no copies.
SAVE_MENTIONS = """
UNWIND $mentions AS mention
MATCH (document:Document {document_id: $document_id})
MATCH (entity) WHERE elementId(entity) = mention.element_id
MERGE (document)-[edge:MENTIONS {page_number: mention.page_number}]->(entity)
SET edge.value_as_written = mention.value_as_written, edge.match_method = mention.match_method,
    edge.source = "llm_extraction"
"""


# --- Part 4: chunks and text search (Step 7) ---------------------------------
#
# Scores: Neo4j gives cosine similarity on a 0 to 1 scale: 1 = same meaning,
# about 0.5 = unrelated. (It is (1 + cosine) / 2 of the usual -1 to 1 cosine.)

SAVE_CHUNKS = """
UNWIND $chunks AS chunk
MATCH (document:Document {document_id: chunk.document_id})
MERGE (piece:Chunk {chunk_id: chunk.chunk_id})
SET piece.text = chunk.text, piece.page_number = chunk.page_number,
    piece.chunk_number = chunk.chunk_number, piece.embedding = chunk.embedding
MERGE (document)-[:HAS_CHUNK]->(piece)
"""

# GraphRAG: the graph gives the claims ($claim_ids); we compare the question only with
# the chunks of those claims. The set is small, so we score every chunk exactly
# (no index needed, and no chunk of these claims can be missed).
SEARCH_CHUNKS_IN_CLAIMS = """
MATCH (claim:Claim)-[:HAS_DOCUMENT]->(document:Document)-[:HAS_CHUNK]->(piece:Chunk)
WHERE claim.claim_id IN $claim_ids
WITH claim, document, piece, vector.similarity.cosine(piece.embedding, $embedding) AS score
ORDER BY score DESC, piece.chunk_id
LIMIT $limit
RETURN claim.claim_id AS claim_id, document.document_id AS document_id,
       document.file_name AS file_name, piece.page_number AS page_number,
       piece.chunk_id AS chunk_id, piece.text AS text, score
"""

# Near-copies of one claim's text in other claims, same kind of document only
# (a story is compared with stories, not with repair estimates).
FIND_COPIED_TEXT = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(own_document:Document)-[:HAS_CHUNK]->(own:Chunk)
MATCH (other_claim:Claim)-[:HAS_DOCUMENT]->(other_document:Document)-[:HAS_CHUNK]->(other:Chunk)
WHERE other_claim.claim_id IN $other_claim_ids AND other_claim.claim_id <> $claim_id
  AND own_document.document_type IN $document_types
  AND other_document.document_type = own_document.document_type
WITH own, own_document, other, other_document, other_claim,
     vector.similarity.cosine(own.embedding, other.embedding) AS score
WHERE score >= $min_score
RETURN own_document.document_id AS document_id, own.page_number AS page_number,
       other_claim.claim_id AS other_claim_id, other_document.document_id AS other_document_id,
       other.page_number AS other_page_number, score, own.text AS text
ORDER BY score DESC, document_id, other_document_id
"""

# The vector index finds the most similar chunks among ALL chunks, fast, without
# comparing every pair. Used to look for copied text across the whole portfolio.
FIND_SIMILAR_CHUNKS_ANYWHERE = """
MATCH (source_document:Document)-[:HAS_CHUNK]->(source:Chunk {chunk_id: $chunk_id})
CALL db.index.vector.queryNodes($index_name, $candidate_count, source.embedding)
YIELD node AS piece, score
MATCH (claim:Claim)-[:HAS_DOCUMENT]->(document:Document)-[:HAS_CHUNK]->(piece)
WHERE document <> source_document
RETURN claim.claim_id AS claim_id, document.document_id AS document_id,
       piece.page_number AS page_number, piece.chunk_id AS chunk_id, score
ORDER BY score DESC
LIMIT $limit
"""

COUNT_CHUNKS_OF_CLAIMS = """
MATCH (claim:Claim)-[:HAS_DOCUMENT]->(:Document)-[:HAS_CHUNK]->(piece:Chunk)
WHERE claim.claim_id IN $claim_ids
RETURN count(piece) AS count
"""


# --- Part 5: lawsuits (Step 8) ----------------------------------------------
#
# Dates go out as text (toString) so the state holds plain values that print well.
# duration.inDays(a, b).days = the number of days from date a to date b.

LAWSUITS_OF_CLAIMS = """
MATCH (claim:Claim)-[:LED_TO]->(lawsuit:Lawsuit)
WHERE claim.claim_id IN $claim_ids
OPTIONAL MATCH (lawsuit)-[:PLAINTIFF_COUNSEL]->(firm:LawFirm)
OPTIONAL MATCH (lawsuit)-[:USES_EXPERT]->(expert:Expert)
RETURN claim.claim_id AS claim_id, lawsuit.lawsuit_id AS lawsuit_id,
       toString(lawsuit.filed_date) AS filed_date,
       toString(lawsuit.limitation_deadline) AS limitation_deadline,
       duration.inDays(lawsuit.filed_date, lawsuit.limitation_deadline).days AS days_before_deadline,
       lawsuit.demand_amount AS demand_amount, lawsuit.status AS status,
       firm.law_firm_id AS law_firm_id, firm.name AS law_firm_name,
       expert.expert_id AS expert_id, expert.name AS expert_name
ORDER BY claim_id, lawsuit_id
"""

# Other claims whose lawsuit has the same plaintiff law firm OR the same expert.
CLAIMS_WITH_RELATED_LAWSUITS = """
MATCH (:Claim {claim_id: $claim_id})-[:LED_TO]->(own:Lawsuit)
MATCH (other_claim:Claim)-[:LED_TO]->(other:Lawsuit)
WHERE other <> own
  AND (EXISTS { MATCH (own)-[:PLAINTIFF_COUNSEL]->(:LawFirm)<-[:PLAINTIFF_COUNSEL]-(other) }
       OR EXISTS { MATCH (own)-[:USES_EXPERT]->(:Expert)<-[:USES_EXPERT]-(other) })
RETURN DISTINCT other_claim.claim_id AS claim_id
ORDER BY claim_id
"""

COUNT_LAWSUITS_OF_CLAIMS = """
MATCH (claim:Claim)-[:LED_TO]->(lawsuit:Lawsuit)
WHERE claim.claim_id IN $claim_ids
RETURN count(lawsuit) AS count
"""


# --- Part 6: Challenger facts and saving the result (Step 9) -----------------
#
# Facts that can give an innocent reason for a shared phone or address:
# a family in one car often shares a last name, a policy, a vehicle and a loss date.
HOUSEHOLD_FACTS = """
MATCH (claimant:Claimant)-[:FILED]->(claim:Claim {claim_id: $claim_id})
MATCH (other_claimant:Claimant)-[:FILED]->(other_claim:Claim)
WHERE other_claim.claim_id IN $other_claim_ids
RETURN other_claim.claim_id AS claim_id,
       other_claimant.last_name = claimant.last_name AS same_last_name,
       EXISTS { MATCH (claim)-[:UNDER]->(:Policy)<-[:UNDER]-(other_claim) } AS same_policy,
       EXISTS { MATCH (claim)-[:INVOLVES]->(:Vehicle)<-[:INVOLVES]-(other_claim) } AS same_vehicle,
       other_claim.loss_date = claim.loss_date AS same_loss_date
ORDER BY claim_id
"""

# How many claims in the whole portfolio use the same repair shop, clinic or law firm.
# A very busy partner gives an innocent reason for many shared claims.
PARTNER_CLAIM_COUNTS = """
MATCH (:Claim {claim_id: $claim_id})-[:REPAIRED_AT|TREATED_BY]->(provider:Provider)
RETURN provider.type AS kind, provider.name AS name,
       COUNT { MATCH (provider)<-[:REPAIRED_AT|TREATED_BY]-(:Claim) } AS claim_count
UNION ALL
MATCH (:Claim {claim_id: $claim_id})-[:REPRESENTED_BY]->(:Attorney)-[:WORKS_AT]->(firm:LawFirm)
RETURN "law_firm" AS kind, firm.name AS name,
       COUNT { MATCH (firm)<-[:WORKS_AT]-(:Attorney)<-[:REPRESENTED_BY]-(:Claim) } AS claim_count
"""

COUNT_CLAIMS = """
MATCH (claim:Claim) RETURN count(claim) AS count
"""

# The portfolio questions (Step 11) read these three properties.
SAVE_INVESTIGATION_RESULT = """
MATCH (claim:Claim {claim_id: $claim_id})
SET claim.risk_score = $risk_score, claim.last_investigated = date($investigated_on),
    claim.summary = $summary
"""
