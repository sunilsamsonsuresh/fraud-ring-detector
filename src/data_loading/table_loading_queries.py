"""The Cypher queries that load the CSV tables into the graph. Each query is a named constant.

Values come in as parameters ($rows, $pairs). No query is built by joining strings. A label or an edge
type cannot be a parameter in Cypher, so each node type and each edge type has its own query.

How to read a query:
  UNWIND $rows AS row   repeat the rest of the query once for each row of the list
  MERGE                 find the node with this ID, or create it. Running twice gives no copies.
  SET                   write the other properties. date(), toFloat() and toInteger() turn CSV text
                        into real types. toFloat("") gives null, and a null property is not stored.
  An optional date uses CASE ... WHEN "" THEN null, because date("") is an error in Cypher.
"""

# --- Nodes: one query for each table ------------------------------------------------------

LOAD_ADDRESSES = """
UNWIND $rows AS row
MERGE (address:Address {address_id: row.address_id})
SET address.street = row.street, address.city = row.city,
    address.state = row.state, address.zip_code = row.zip_code
"""

# There is no phones table. The claimants table holds the numbers. A shared phone is one node.
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

# The graph has no Settlement node. A settlement is stored on its Lawsuit node.
# MATCH (not MERGE): the lawsuits must exist first, so this query runs after LOAD_LAWSUITS.
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

# --- Edges: one query for each kind of link ---------------------------------------------------
# Each item of $pairs is {from_id: ..., to_id: ...}. MATCH (not MERGE) finds both nodes: a missing
# node means no edge, and never a fake empty node.

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

# --- Counts, to check a load ------------------------------------------------------------------
# labels(n)[0] is the first (and only) label of a node.

COUNT_NODES_BY_LABEL = """
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count
"""

COUNT_EDGES_BY_TYPE = """
MATCH ()-[edge]->() RETURN type(edge) AS edge_type, count(*) AS count
"""
