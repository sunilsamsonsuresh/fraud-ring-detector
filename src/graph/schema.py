"""Create the Neo4j schema: constraints and indexes (PLAN.md A5, PLAN-v2.md A5).

Run it:  python -m src.graph.schema
Every statement uses IF NOT EXISTS, so running it twice is safe.

Schema statements cannot take $parameters for labels or names, so each
statement is written out in full. No statement is built by joining strings.

--- Nodes (label: unique ID property) ---
Claimant  : claimant_id   A person who files a claim.
Claim     : claim_id      One auto injury claim. Example: "C-1001".
Policy    : policy_id     The insurance policy of the claim.
Vehicle   : vehicle_id    A vehicle in the accident. The VIN is a normal property.
Address   : address_id    A home address. People who share an address share this node.
Phone     : number        A phone number in one fixed format. Example: "555-0142".
                          The number itself is the ID, so a shared phone is one node.
Provider  : provider_id   A repair shop, clinic or doctor. Property `type` says which.
Attorney  : attorney_id   A lawyer on a claim.
LawFirm   : law_firm_id   The firm an attorney works at.
Lawsuit   : lawsuit_id    A lawsuit that came from a claim.
Court     : court_id      The court where the lawsuit was filed.
Expert    : expert_id     An expert witness in a lawsuit.
Payment   : payment_id    A payment made on a claim.
Document  : document_id   One PDF in the claim file.
Chunk     : chunk_id      A piece of text from a Document, with an embedding.

--- Nodes added in v2 ---
Incident      : incident_id   One real-world accident. Many claims can come from one incident.
Treatment     : treatment_id  One medical visit: visit_date, procedure_group, charge.
ReserveEvent  : event_id      One change of a claim's reserve: event_date, reserve_total.
Finding       : finding_id    One rated fact read from a PDF: feature, value, severity_rank,
                              confidence, quote, page_number, note_date.
ScoreSnapshot : snapshot_id   One saved score of one claim on one date (claim_id, as_of_date,
                              total_score, band, category scores, coverage_pct, fired rules).

--- Edges ---
(Claimant)-[:FILED]->(Claim)                 who filed the claim
(Claim)-[:UNDER]->(Policy)                   policy of the claim
(Claim)-[:INVOLVES]->(Vehicle)               vehicle in the loss
(Claimant)-[:LIVES_AT]->(Address)            home address
(Claimant)-[:HAS_PHONE]->(Phone)             phone number
(Claim)-[:REPAIRED_AT]->(Provider)           repair shop
(Claim)-[:TREATED_BY]->(Provider)            clinic or doctor
(Claim)-[:REPRESENTED_BY]->(Attorney)        attorney on the claim
(Attorney)-[:WORKS_AT]->(LawFirm)            law firm
(Claim)-[:LED_TO]->(Lawsuit)                 lawsuit from the claim
(Lawsuit)-[:FILED_IN]->(Court)               court
(Lawsuit)-[:PLAINTIFF_COUNSEL]->(LawFirm)    plaintiff law firm
(Lawsuit)-[:USES_EXPERT]->(Expert)           expert witness
(Claim)-[:HAS_PAYMENT]->(Payment)            payment on the claim
(Claim)-[:HAS_DOCUMENT]->(Document)          document in the claim file
(Document)-[:HAS_CHUNK]->(Chunk)             text piece with an embedding
(Document)-[:MENTIONS]->(any entity)         entity found in a PDF. Stores `page`.

--- Edges added in v2 ---
(Claim)-[:ARISES_FROM]->(Incident)           the claim belongs to one incident
(Claim)-[:HAS_TREATMENT]->(Treatment)        a visit
(Treatment)-[:BY_PROVIDER]->(Provider)       who treated
(Claim)-[:HAS_RESERVE_EVENT]->(ReserveEvent) reserve history
(Claim)-[:HAS_FINDING]->(Finding)            a rated fact from a PDF
(Finding)-[:FOUND_IN]->(Document)            where the proof is (the finding holds the quote and page)
(Claim)-[:HAS_SCORE]->(ScoreSnapshot)        score history

Trust: edges made from the CSV tables are high trust. MENTIONS edges come
from the LLM reading PDFs, so they are medium trust and always keep their source.
Edges need no schema statements: Neo4j creates edge types when data is loaded.
"""

from neo4j import Driver

from src import config
from src.graph.connection import open_neo4j_driver

# One uniqueness constraint per node type. It stops duplicate nodes
# (two Claim nodes for "C-1001"), and it also makes lookups by ID fast.
UNIQUE_ID_CONSTRAINTS = [
    "CREATE CONSTRAINT claimant_id_unique IF NOT EXISTS FOR (n:Claimant) REQUIRE n.claimant_id IS UNIQUE",
    "CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (n:Claim) REQUIRE n.claim_id IS UNIQUE",
    "CREATE CONSTRAINT policy_id_unique IF NOT EXISTS FOR (n:Policy) REQUIRE n.policy_id IS UNIQUE",
    "CREATE CONSTRAINT vehicle_id_unique IF NOT EXISTS FOR (n:Vehicle) REQUIRE n.vehicle_id IS UNIQUE",
    "CREATE CONSTRAINT address_id_unique IF NOT EXISTS FOR (n:Address) REQUIRE n.address_id IS UNIQUE",
    "CREATE CONSTRAINT phone_number_unique IF NOT EXISTS FOR (n:Phone) REQUIRE n.number IS UNIQUE",
    "CREATE CONSTRAINT provider_id_unique IF NOT EXISTS FOR (n:Provider) REQUIRE n.provider_id IS UNIQUE",
    "CREATE CONSTRAINT attorney_id_unique IF NOT EXISTS FOR (n:Attorney) REQUIRE n.attorney_id IS UNIQUE",
    "CREATE CONSTRAINT law_firm_id_unique IF NOT EXISTS FOR (n:LawFirm) REQUIRE n.law_firm_id IS UNIQUE",
    "CREATE CONSTRAINT lawsuit_id_unique IF NOT EXISTS FOR (n:Lawsuit) REQUIRE n.lawsuit_id IS UNIQUE",
    "CREATE CONSTRAINT court_id_unique IF NOT EXISTS FOR (n:Court) REQUIRE n.court_id IS UNIQUE",
    "CREATE CONSTRAINT expert_id_unique IF NOT EXISTS FOR (n:Expert) REQUIRE n.expert_id IS UNIQUE",
    "CREATE CONSTRAINT payment_id_unique IF NOT EXISTS FOR (n:Payment) REQUIRE n.payment_id IS UNIQUE",
    "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (n:Document) REQUIRE n.document_id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE",
    # v2 nodes
    "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS FOR (n:Incident) REQUIRE n.incident_id IS UNIQUE",
    "CREATE CONSTRAINT treatment_id_unique IF NOT EXISTS FOR (n:Treatment) REQUIRE n.treatment_id IS UNIQUE",
    "CREATE CONSTRAINT reserve_event_id_unique IF NOT EXISTS FOR (n:ReserveEvent) REQUIRE n.event_id IS UNIQUE",
    "CREATE CONSTRAINT finding_id_unique IF NOT EXISTS FOR (n:Finding) REQUIRE n.finding_id IS UNIQUE",
    "CREATE CONSTRAINT score_snapshot_id_unique IF NOT EXISTS FOR (n:ScoreSnapshot) REQUIRE n.snapshot_id IS UNIQUE",
]

# Indexes for searches that do not use the ID. The Intake agent and the
# Question Router look up people and companies by name (PLAN.md A9),
# and match people by name plus date of birth (Step 6).
LOOKUP_INDEXES = [
    "CREATE INDEX claimant_name_index IF NOT EXISTS FOR (n:Claimant) ON (n.last_name, n.first_name)",
    "CREATE INDEX claimant_birth_date_index IF NOT EXISTS FOR (n:Claimant) ON (n.date_of_birth)",
    "CREATE INDEX provider_name_index IF NOT EXISTS FOR (n:Provider) ON (n.name)",
    "CREATE INDEX attorney_name_index IF NOT EXISTS FOR (n:Attorney) ON (n.name)",
    "CREATE INDEX law_firm_name_index IF NOT EXISTS FOR (n:LawFirm) ON (n.name)",
    "CREATE INDEX expert_name_index IF NOT EXISTS FOR (n:Expert) ON (n.name)",
    # v2: findings by feature, score history by claim and date, claims by loss date (score as of a date)
    "CREATE INDEX finding_feature_index IF NOT EXISTS FOR (n:Finding) ON (n.feature)",
    "CREATE INDEX score_snapshot_claim_index IF NOT EXISTS FOR (n:ScoreSnapshot) ON (n.claim_id)",
    "CREATE INDEX score_snapshot_date_index IF NOT EXISTS FOR (n:ScoreSnapshot) ON (n.as_of_date)",
    "CREATE INDEX claim_loss_date_index IF NOT EXISTS FOR (n:Claim) ON (n.loss_date)",
]

# The vector index lets Neo4j find the chunks whose embedding is closest to
# the embedding of a question (GraphRAG, PLAN.md A7). The size must match the
# embedding model. Neo4j does not allow a $parameter here, so the number is
# written in the text; the test checks that it equals EMBEDDING_DIMENSIONS.
CHUNK_VECTOR_INDEX = (
    "CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS "
    "FOR (n:Chunk) ON (n.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}"
)
CHUNK_VECTOR_INDEX_NAME = "chunk_embedding_index"


def create_schema(driver: Driver) -> None:
    """Create all constraints and indexes. Safe to run many times."""
    all_statements = UNIQUE_ID_CONSTRAINTS + LOOKUP_INDEXES + [CHUNK_VECTOR_INDEX]
    for statement in all_statements:
        driver.execute_query(statement)


if __name__ == "__main__":
    try:
        neo4j_driver = open_neo4j_driver()
    except RuntimeError as error:
        print(f"Error: {error}")
        raise SystemExit(1)

    try:
        create_schema(neo4j_driver)
    finally:
        neo4j_driver.close()

    print(
        f"Schema ready: {len(UNIQUE_ID_CONSTRAINTS)} constraints, "
        f"{len(LOOKUP_INDEXES)} lookup indexes, 1 vector index "
        f"({config.EMBEDDING_DIMENSIONS} dimensions)."
    )
