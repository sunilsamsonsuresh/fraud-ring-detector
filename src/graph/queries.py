"""All Cypher queries of the project, as named constants (CLAUDE.md, rule 5.2).

Values always come in as parameters ($rows, $pairs). No query is built by
joining strings. Labels and edge types cannot be parameters in Cypher, so
each node type and each edge type has its own query.

Part 1 (Step 4): loading the CSV tables.
Part 2 (Step 5): the fixed investigation templates.
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
