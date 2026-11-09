"""All Cypher queries of the project, as named constants (CLAUDE.md, rule 5.2).

Values always come in as parameters ($rows, $pairs). No query is built by
joining strings. Labels and edge types cannot be parameters in Cypher, so
each node type and each edge type has its own query.

Part 1 (Step 4): loading the CSV tables.
Part 2 (Step 5): the fixed investigation templates.
Part 3 (Step 6): documents and the entities they mention.
Part 4 (Step 7): chunks and text search.
Part 5 (Step 8): lawsuits.
Part 6 (Step 9, V12): saving the investigation result.
Part 7 (V5): loading the v2 tables (incidents, treatments, reserve events, new dates).
Part 8 (V6): findings and the loss date written in each document.
Part 9 (V7): the facts of one claim for the scoring engine, and the score snapshot.
Part 10 (V8): the network templates for the NL rules.
Part 11 (V11, V12): Challenger checks, litigation facts and the workflow.
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

# v2 adds the customer and coverage dates. An empty CSV cell must become null, and date("")
# is an error in Cypher, so each optional date uses CASE ... WHEN "" THEN null.
LOAD_POLICIES = """
UNWIND $rows AS row
MERGE (policy:Policy {policy_id: row.policy_id})
SET policy.effective_date = date(row.effective_date),
    policy.expiration_date = date(row.expiration_date),
    policy.bodily_injury_limit = toInteger(row.bodily_injury_limit),
    policy.customer_since = CASE row.customer_since WHEN "" THEN null ELSE date(row.customer_since) END,
    policy.last_coverage_increase_date = CASE row.last_coverage_increase_date WHEN "" THEN null
                                         ELSE date(row.last_coverage_increase_date) END,
    policy.lapse_start = CASE row.lapse_start WHEN "" THEN null ELSE date(row.lapse_start) END,
    policy.lapse_end = CASE row.lapse_end WHEN "" THEN null ELSE date(row.lapse_end) END,
    policy.per_person_limit = toInteger(row.per_person_limit),
    policy.per_accident_limit = toInteger(row.per_accident_limit)
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
    claim.medical_bill_amount = toFloat(row.medical_bill_amount),
    claim.close_date = CASE row.close_date WHEN "" THEN null ELSE date(row.close_date) END,
    claim.attorney_retained_date = CASE row.attorney_retained_date WHEN "" THEN null
                                   ELSE date(row.attorney_retained_date) END
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


# --- Part 6: saving the investigation result (Step 9, V12) --------------------

# The portfolio questions (V14) read these properties. (The v1 Challenger queries were removed in V11.)
SAVE_INVESTIGATION_RESULT = """
MATCH (claim:Claim {claim_id: $claim_id})
SET claim.risk_score = $risk_score, claim.band = $band, claim.last_investigated = date($investigated_on),
    claim.summary = $summary
"""


# --- Part 7: loading the v2 tables (V5) ---------------------------------------

LOAD_INCIDENTS = """
UNWIND $rows AS row
MERGE (incident:Incident {incident_id: row.incident_id})
SET incident.loss_date = date(row.loss_date), incident.location_text = row.location_text
"""

LOAD_TREATMENTS = """
UNWIND $rows AS row
MERGE (visit:Treatment {treatment_id: row.treatment_id})
SET visit.visit_date = date(row.visit_date), visit.procedure_group = row.procedure_group,
    visit.charge = toFloat(row.charge)
"""

LOAD_RESERVE_EVENTS = """
UNWIND $rows AS row
MERGE (event:ReserveEvent {event_id: row.event_id})
SET event.event_date = date(row.event_date), event.reserve_total = toFloat(row.reserve_total)
"""

LINK_CLAIM_ARISES_FROM_INCIDENT = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (incident:Incident {incident_id: pair.to_id})
MERGE (claim)-[:ARISES_FROM]->(incident)
"""

LINK_CLAIM_HAS_TREATMENT = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (visit:Treatment {treatment_id: pair.to_id})
MERGE (claim)-[:HAS_TREATMENT]->(visit)
"""

LINK_TREATMENT_BY_PROVIDER = """
UNWIND $pairs AS pair
MATCH (visit:Treatment {treatment_id: pair.from_id}) MATCH (provider:Provider {provider_id: pair.to_id})
MERGE (visit)-[:BY_PROVIDER]->(provider)
"""

LINK_CLAIM_HAS_RESERVE_EVENT = """
UNWIND $pairs AS pair
MATCH (claim:Claim {claim_id: pair.from_id}) MATCH (event:ReserveEvent {event_id: pair.to_id})
MERGE (claim)-[:HAS_RESERVE_EVENT]->(event)
"""

# The claims of one incident, with their claimants. Example: one honest multi-claimant accident.
CLAIMS_OF_INCIDENT = """
MATCH (claimant:Claimant)-[:FILED]->(claim:Claim)-[:ARISES_FROM]->(incident:Incident {incident_id: $incident_id})
RETURN incident.incident_id AS incident_id, incident.loss_date AS loss_date,
       incident.location_text AS location_text, claim.claim_id AS claim_id,
       claimant.first_name + " " + claimant.last_name AS claimant_name
ORDER BY claim_id
"""


# --- Part 8: findings and document loss dates (V6) ------------------------------
#
# Rule AS-7 (V7) reads the loss date of each document. A document with no readable loss
# date gets null, null and false.
SAVE_DOCUMENT_LOSS_DATE = """
MATCH (document:Document {document_id: $document_id})
SET document.loss_date_in_pdf = $loss_date_in_pdf, document.loss_date_page_number = $page_number,
    document.loss_date_conflict = $loss_date_conflict
"""

# A new reading replaces the old findings of the document (only Finding nodes, only this document).
DELETE_FINDINGS_OF_DOCUMENT = """
MATCH (:Document {document_id: $document_id})<-[:FOUND_IN]-(finding:Finding)
DETACH DELETE finding
"""

SAVE_FINDINGS = """
MATCH (claim:Claim {claim_id: $claim_id})
MATCH (document:Document {document_id: $document_id})
UNWIND $findings AS item
MERGE (finding:Finding {finding_id: item.finding_id})
SET finding.feature = item.feature, finding.value = item.value, finding.severity_rank = item.severity_rank,
    finding.confidence = item.confidence, finding.quote = item.quote, finding.reason = item.reason,
    finding.page_number = item.page_number, finding.note_date = item.note_date,
    finding.document_type = $document_type, finding.source = "llm_extraction"
MERGE (claim)-[:HAS_FINDING]->(finding)
MERGE (finding)-[:FOUND_IN]->(document)
"""

FINDINGS_OF_CLAIM = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_FINDING]->(finding:Finding)-[:FOUND_IN]->(document:Document)
RETURN finding.finding_id AS finding_id, finding.feature AS feature, finding.value AS value,
       finding.severity_rank AS severity_rank, finding.confidence AS confidence, finding.quote AS quote,
       finding.page_number AS page_number, finding.note_date AS note_date, document.document_id AS document_id,
       document.document_type AS document_type
ORDER BY finding_id
"""


# --- Part 9: the facts of one claim for the scoring engine, and the score snapshot (V7) --
#
# Dates come back as Neo4j dates; src/scoring/facts.py turns them into Python dates.
# OPTIONAL MATCH: a claim with no policy or no incident still returns one row (with nulls).
# incident_claims: [claimant ID, reported date] for every claim of the incident. Plain code
# counts the claimants (V9: only the claims reported by a given date).

SCORING_CLAIM_FACTS = """
MATCH (claim:Claim {claim_id: $claim_id})
OPTIONAL MATCH (claim)-[:UNDER]->(policy:Policy)
OPTIONAL MATCH (claim)-[:ARISES_FROM]->(incident:Incident)
OPTIONAL MATCH (incident)<-[:ARISES_FROM]-(incident_claim:Claim)<-[:FILED]-(person:Claimant)
WITH claim, policy, incident,
     [pair IN collect([person.claimant_id, incident_claim.reported_date]) WHERE pair[0] IS NOT NULL] AS incident_claims
RETURN claim.claim_id AS claim_id, claim.loss_date AS loss_date, claim.reported_date AS reported_date,
       claim.attorney_retained_date AS attorney_retained_date,
       claim.repair_estimate_amount AS repair_estimate_amount,
       policy.policy_id AS policy_id, policy.effective_date AS effective_date,
       policy.expiration_date AS expiration_date, policy.customer_since AS customer_since,
       policy.last_coverage_increase_date AS last_coverage_increase_date,
       policy.lapse_start AS lapse_start, policy.lapse_end AS lapse_end,
       incident.incident_id AS incident_id, incident_claims
"""

SCORING_VISIT_DATES = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_TREATMENT]->(visit:Treatment)
RETURN visit.visit_date AS visit_date
ORDER BY visit_date, visit.treatment_id
"""

SCORING_PAYMENTS = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_PAYMENT]->(payment:Payment)
RETURN payment.payment_id AS payment_id, payment.payment_date AS payment_date, payment.amount AS amount,
       payment.payment_type AS payment_type
ORDER BY payment_date, payment_id
"""

SCORING_RESERVE_EVENTS = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_RESERVE_EVENT]->(event:ReserveEvent)
RETURN event.event_id AS event_id, event.event_date AS event_date, event.reserve_total AS reserve_total
ORDER BY event_date, event_id
"""

SCORING_LAWSUITS = """
MATCH (:Claim {claim_id: $claim_id})-[:LED_TO]->(lawsuit:Lawsuit)
RETURN lawsuit.lawsuit_id AS lawsuit_id, lawsuit.filed_date AS filed_date,
       lawsuit.limitation_deadline AS limitation_deadline, lawsuit.settlement_date AS settlement_date
ORDER BY lawsuit_id
"""

SCORING_DOCUMENT_LOSS_DATES = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(document:Document)
RETURN document.document_id AS document_id, document.document_type AS document_type,
       document.loss_date_in_pdf AS loss_date_in_pdf,
       document.loss_date_page_number AS page_number, document.loss_date_conflict AS conflict
ORDER BY document_id
"""

ALL_CLAIM_IDS = """
MATCH (claim:Claim) RETURN claim.claim_id AS claim_id ORDER BY claim_id
"""

# One snapshot per claim and date: scoring again on the same date replaces it.
SAVE_SCORE_SNAPSHOT = """
MATCH (claim:Claim {claim_id: $claim_id})
MERGE (snapshot:ScoreSnapshot {snapshot_id: $snapshot_id})
SET snapshot.claim_id = $claim_id, snapshot.as_of_date = date($as_of_date),
    snapshot.total_score = $total_score, snapshot.band = $band,
    snapshot.bi_score = $bi_score, snapshot.as_score = $as_score, snapshot.bf_score = $bf_score,
    snapshot.ct_score = $ct_score, snapshot.nl_score = $nl_score, snapshot.coverage_pct = $coverage_pct,
    snapshot.fired_rule_ids = $fired_rule_ids, snapshot.fired_rules_json = $fired_rules_json
MERGE (claim)-[:HAS_SCORE]->(snapshot)
"""

SNAPSHOTS_OF_CLAIM = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
RETURN snapshot.snapshot_id AS snapshot_id, snapshot.total_score AS total_score, snapshot.band AS band,
       snapshot.fired_rule_ids AS fired_rule_ids, snapshot.is_peak AS is_peak
ORDER BY snapshot_id
"""


# --- Part 10: network templates for the NL rules (V8) ------------------------
#
# Every template here ignores links between claims of the SAME incident (CLAUDE.md, rule 20):
#   NOT EXISTS { (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
# A strong link (A7) is: (a) a phone, (b) an address, (c) the same clinic AND the same attorney,
# or (d) the same law firm AND the same expert. Each kind has its own template.
# The four strong-link templates take a LIST of claims ($claim_ids), so one call can serve
# one hop of the cluster search, and they return the same columns.
# Two MATCH clauses on purpose (see Part 2): one claimant with two claims shares one HAS_PHONE edge.
# provider_claim_count: how many claims use the shared clinic (or lawsuits the shared law firm);
# the Challenger's busy-provider check reads it (V11). null for a phone or an address.

NL_LINKS_SHARED_PHONE = """
MATCH (source:Claim)<-[:FILED]-(:Claimant)-[:HAS_PHONE]->(phone:Phone)
MATCH (phone)<-[:HAS_PHONE]-(:Claimant)-[:FILED]->(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id, "phone" AS kind,
       phone.number AS shared_value, linked.reported_date AS linked_reported_date,
       null AS source_filed_date, null AS linked_filed_date, null AS provider_claim_count
ORDER BY source_claim_id, linked_claim_id
"""

NL_LINKS_SHARED_ADDRESS = """
MATCH (source:Claim)<-[:FILED]-(:Claimant)-[:LIVES_AT]->(address:Address)
MATCH (address)<-[:LIVES_AT]-(:Claimant)-[:FILED]->(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id, "address" AS kind,
       address.street + ", " + address.city AS shared_value, linked.reported_date AS linked_reported_date,
       null AS source_filed_date, null AS linked_filed_date, null AS provider_claim_count
ORDER BY source_claim_id, linked_claim_id
"""

NL_LINKS_CLINIC_AND_ATTORNEY = """
MATCH (source:Claim)-[:TREATED_BY]->(clinic:Provider)
MATCH (clinic)<-[:TREATED_BY]-(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
MATCH (source)-[:REPRESENTED_BY]->(attorney:Attorney)
MATCH (attorney)<-[:REPRESENTED_BY]-(linked)
WHERE NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       "clinic_and_attorney" AS kind, clinic.name + " + " + attorney.name AS shared_value,
       linked.reported_date AS linked_reported_date, null AS source_filed_date, null AS linked_filed_date,
       COUNT { MATCH (clinic)<-[:TREATED_BY]-(:Claim) } AS provider_claim_count
ORDER BY source_claim_id, linked_claim_id
"""

# (d) compares the lawsuits: the plaintiff law firm and the expert of both suits.
NL_LINKS_FIRM_AND_EXPERT = """
MATCH (source:Claim)-[:LED_TO]->(own:Lawsuit)-[:PLAINTIFF_COUNSEL]->(firm:LawFirm)
MATCH (firm)<-[:PLAINTIFF_COUNSEL]-(other:Lawsuit)<-[:LED_TO]-(linked:Claim)
WHERE source.claim_id IN $claim_ids AND linked <> source
MATCH (own)-[:USES_EXPERT]->(expert:Expert)
MATCH (expert)<-[:USES_EXPERT]-(other)
WHERE NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(linked) }
RETURN DISTINCT source.claim_id AS source_claim_id, linked.claim_id AS linked_claim_id,
       "firm_and_expert" AS kind, firm.name + " + " + expert.name AS shared_value,
       linked.reported_date AS linked_reported_date, own.filed_date AS source_filed_date,
       other.filed_date AS linked_filed_date, COUNT { MATCH (firm)<-[:PLAINTIFF_COUNSEL]-(:Lawsuit) } AS provider_claim_count
ORDER BY source_claim_id, linked_claim_id
"""

# NL-2: the other claims of the same claimant (in other incidents).
NL_REPEAT_CLAIMS = """
MATCH (source:Claim {claim_id: $claim_id})<-[:FILED]-(person:Claimant)
MATCH (person)-[:FILED]->(other:Claim)
WHERE other <> source
  AND NOT EXISTS { MATCH (source)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(other) }
RETURN other.claim_id AS claim_id, other.loss_date AS loss_date, other.reported_date AS reported_date
ORDER BY claim_id
"""

# NL-4: near-copies of this claim's story chunks in claims of OTHER incidents, anywhere in the
# portfolio. The vector index returns the closest chunks fast; plain Cypher then keeps only
# the same document type, a score at the threshold or above, and other incidents.
NL_COPIED_STORY = """
MATCH (claim:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(own_document:Document)-[:HAS_CHUNK]->(own:Chunk)
WHERE own_document.document_type IN $document_types
CALL db.index.vector.queryNodes($index_name, $candidate_count, own.embedding) YIELD node AS other, score
WITH claim, own_document, own, other, score
WHERE score >= $min_score
MATCH (other_claim:Claim)-[:HAS_DOCUMENT]->(other_document:Document)-[:HAS_CHUNK]->(other)
WHERE other_claim <> claim AND other_document.document_type = own_document.document_type
  AND NOT EXISTS { MATCH (claim)-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(other_claim) }
RETURN own_document.document_id AS document_id, own_document.document_type AS document_type,
       own.page_number AS page_number, other_claim.claim_id AS other_claim_id,
       other_claim.reported_date AS other_reported_date, other_document.document_id AS other_document_id,
       other.page_number AS other_page_number, score, own.text AS text
ORDER BY score DESC, document_id, other_document_id
"""

# NL-4 needs this claim's own story text. No story chunks -> the rule is "not evaluated".
STORY_DOCUMENT_TYPES_OF_CLAIM = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_DOCUMENT]->(document:Document)
WHERE document.document_type IN $document_types AND EXISTS { (document)-[:HAS_CHUNK]->(:Chunk) }
RETURN DISTINCT document.document_type AS document_type
ORDER BY document_type
"""

# V9: exactly one snapshot of the claim is the peak of its score history.
MARK_PEAK_SNAPSHOT = """
MATCH (:Claim {claim_id: $claim_id})-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
SET snapshot.is_peak = (snapshot.snapshot_id = $peak_snapshot_id)
"""


# --- Part 11: Challenger checks, litigation facts and the workflow (V11, V12) -------

# Family link check (A8): same address, same surname, different birth dates.
FAMILY_LINK_FACTS = """
MATCH (person:Claimant)-[:FILED]->(:Claim {claim_id: $claim_id})
MATCH (other_person:Claimant)-[:FILED]->(other_claim:Claim)
WHERE other_claim.claim_id IN $other_claim_ids
RETURN other_claim.claim_id AS claim_id,
       EXISTS { MATCH (person)-[:LIVES_AT]->(:Address)<-[:LIVES_AT]-(other_person) } AS same_address,
       other_person.last_name = person.last_name AS same_last_name,
       other_person.date_of_birth <> person.date_of_birth AS different_birth_date
ORDER BY claim_id
"""

INCIDENT_CLAIM_IDS = """
MATCH (:Claim {claim_id: $claim_id})-[:ARISES_FROM]->(:Incident)<-[:ARISES_FROM]-(other:Claim)
WHERE other.claim_id <> $claim_id
RETURN other.claim_id AS claim_id
ORDER BY claim_id
"""

# Common rule check (A8): how many claims fire each rule in their latest snapshot (from score-all).
RULE_FIRE_COUNTS = """
MATCH (claim:Claim)-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
WITH claim, snapshot ORDER BY snapshot.as_of_date DESC, snapshot.snapshot_id DESC
WITH claim, collect(snapshot)[0] AS latest
UNWIND latest.fired_rule_ids AS rule_id
RETURN rule_id, count(claim) AS claim_count
ORDER BY rule_id
"""

COUNT_SCORED_CLAIMS = """
MATCH (claim:Claim) WHERE EXISTS { (claim)-[:HAS_SCORE]->(:ScoreSnapshot) }
RETURN count(claim) AS count
"""

# Litigation Analyst (V11): the medical bills behind the demand.
LAWSUIT_MEDICAL_FACTS = """
MATCH (claim:Claim {claim_id: $claim_id})
OPTIONAL MATCH (claim)-[:HAS_TREATMENT]->(visit:Treatment)
RETURN claim.medical_bill_amount AS medical_bill_amount, count(visit) AS visit_count,
       sum(visit.charge) AS treatment_charges
"""

# Intake is skipped when the claim's PDFs were already read (V12): findings exist and the
# entity reading set the loss date flag on its documents.
CLAIM_READ_STATUS = """
MATCH (claim:Claim {claim_id: $claim_id})
RETURN COUNT { MATCH (claim)-[:HAS_FINDING]->(:Finding) } AS finding_count,
       COUNT { MATCH (claim)-[:HAS_DOCUMENT]->(document:Document) WHERE document.loss_date_conflict IS NOT NULL }
           AS checked_document_count
"""


# --- Part 12: questions in plain English (V14) --------------------------------
#
# The Question Router never writes Cypher. Plain code checks each value and passes it as a
# parameter to one of these fixed queries.

CLAIM_EXISTS = """
MATCH (claim:Claim {claim_id: $claim_id}) RETURN claim.claim_id AS claim_id
"""

# The latest snapshot of every scored claim (one row per claim), with the investigated band if any.
LATEST_SNAPSHOTS = """
MATCH (claim:Claim)-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
WITH claim, snapshot ORDER BY snapshot.as_of_date DESC, snapshot.snapshot_id DESC
WITH claim, collect(snapshot)[0] AS latest
RETURN claim.claim_id AS claim_id, latest.snapshot_id AS snapshot_id, latest.as_of_date AS as_of_date,
       latest.total_score AS total_score, latest.band AS band, latest.bi_score AS bi_score,
       latest.as_score AS as_score, latest.bf_score AS bf_score, latest.ct_score AS ct_score,
       latest.nl_score AS nl_score, latest.coverage_pct AS coverage_pct, latest.fired_rule_ids AS fired_rule_ids,
       claim.band AS investigated_band, claim.risk_score AS investigated_score
ORDER BY claim_id
"""

LATEST_SNAPSHOT_OF_CLAIM = """
MATCH (claim:Claim {claim_id: $claim_id})-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
RETURN snapshot.snapshot_id AS snapshot_id, snapshot.as_of_date AS as_of_date,
       snapshot.total_score AS total_score, snapshot.band AS band, snapshot.coverage_pct AS coverage_pct,
       snapshot.fired_rules_json AS fired_rules_json, claim.band AS investigated_band,
       claim.risk_score AS investigated_score, claim.summary AS investigated_summary,
       claim.last_investigated AS last_investigated
ORDER BY snapshot.as_of_date DESC, snapshot.snapshot_id DESC
LIMIT 1
"""

# Every snapshot score, for the "rising claims" view (only claims with a score history have several).
ALL_SNAPSHOT_SCORES = """
MATCH (claim:Claim)-[:HAS_SCORE]->(snapshot:ScoreSnapshot)
RETURN claim.claim_id AS claim_id, snapshot.as_of_date AS as_of_date, snapshot.total_score AS total_score
ORDER BY claim_id, as_of_date
"""

# $phone_end is the end of the number ("555-0142" or "713-555-0142"); plain code made it from digits only.
CLAIMS_WITH_PHONE = """
MATCH (phone:Phone)<-[:HAS_PHONE]-(:Claimant)-[:FILED]->(claim:Claim)
WHERE phone.number ENDS WITH $phone_end
RETURN DISTINCT claim.claim_id AS claim_id, phone.number AS shared_value
ORDER BY claim_id
"""

# Claims linked to a clinic, repair shop, attorney or law firm with this name (no case difference).
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
