"""Step 1 of loading the graph: create the schema (constraints and indexes) in Neo4j.

The schema is a set of rules about the data. It must exist BEFORE the first node is loaded.

  * A uniqueness constraint stops two nodes with the same ID. Example: two Claim nodes "C-1001".
    Neo4j also makes a fast lookup by ID from each constraint.
  * A lookup index makes a search by another property fast. Example: a person by last name.
  * The vector index lets Neo4j find the text chunks whose embedding is closest to another
    embedding. Rule NL-4 (copied story) and the document search use it.
  * The full-text index finds the chunks that contain some words, like a search engine.
    The hybrid document search uses it together with the vector index.

Every statement has IF NOT EXISTS. Thus, you can run this file many times: nothing changes
after the first run. A schema statement cannot take $parameters for a label or a name, so each
statement is written out in full. No statement is built by joining strings.

Nodes (label: the property that holds its unique ID)
  Claim: claim_id, Claimant: claimant_id, Incident: incident_id, Policy: policy_id,
  Vehicle: vehicle_id, Address: address_id, Phone: number, Provider: provider_id,
  Attorney: attorney_id, LawFirm: law_firm_id, Lawsuit: lawsuit_id, Court: court_id,
  Expert: expert_id, Payment: payment_id, Treatment: treatment_id, ReserveEvent: event_id
  Document: document_id, Chunk: chunk_id, Finding: finding_id, ScoreSnapshot: snapshot_id,
  Community: community_id

The first 16 come from the CSV tables (load_tables_into_graph.py). Document, Chunk and Finding come
from the PDFs. ScoreSnapshot is a saved score. Community is a group of linked claims.
"""

from neo4j import Driver

# One uniqueness constraint for each node label.
UNIQUE_ID_CONSTRAINTS = [
    "CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (n:Claim) REQUIRE n.claim_id IS UNIQUE",
    "CREATE CONSTRAINT claimant_id_unique IF NOT EXISTS FOR (n:Claimant) REQUIRE n.claimant_id IS UNIQUE",
    "CREATE CONSTRAINT incident_id_unique IF NOT EXISTS FOR (n:Incident) REQUIRE n.incident_id IS UNIQUE",
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
    "CREATE CONSTRAINT treatment_id_unique IF NOT EXISTS FOR (n:Treatment) REQUIRE n.treatment_id IS UNIQUE",
    "CREATE CONSTRAINT reserve_event_id_unique IF NOT EXISTS FOR (n:ReserveEvent) REQUIRE n.event_id IS UNIQUE",
    "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (n:Document) REQUIRE n.document_id IS UNIQUE",
    "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE",
    "CREATE CONSTRAINT finding_id_unique IF NOT EXISTS FOR (n:Finding) REQUIRE n.finding_id IS UNIQUE",
    "CREATE CONSTRAINT score_snapshot_id_unique IF NOT EXISTS FOR (n:ScoreSnapshot) REQUIRE n.snapshot_id IS UNIQUE",
]

# Community nodes come from build step 5 (src/data_loading/load_communities_into_graph.py).
COMMUNITY_CONSTRAINT = "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (n:Community) REQUIRE n.community_id IS UNIQUE"

# Indexes for searches that do not use the ID.
LOOKUP_INDEXES = [
    "CREATE INDEX claimant_name_index IF NOT EXISTS FOR (n:Claimant) ON (n.last_name, n.first_name)",
    "CREATE INDEX claimant_birth_date_index IF NOT EXISTS FOR (n:Claimant) ON (n.date_of_birth)",
    "CREATE INDEX provider_name_index IF NOT EXISTS FOR (n:Provider) ON (n.name)",
    "CREATE INDEX attorney_name_index IF NOT EXISTS FOR (n:Attorney) ON (n.name)",
    "CREATE INDEX law_firm_name_index IF NOT EXISTS FOR (n:LawFirm) ON (n.name)",
    "CREATE INDEX expert_name_index IF NOT EXISTS FOR (n:Expert) ON (n.name)",
    "CREATE INDEX claim_loss_date_index IF NOT EXISTS FOR (n:Claim) ON (n.loss_date)",
    "CREATE INDEX finding_feature_index IF NOT EXISTS FOR (n:Finding) ON (n.feature)",
    "CREATE INDEX score_snapshot_claim_index IF NOT EXISTS FOR (n:ScoreSnapshot) ON (n.claim_id)",
    "CREATE INDEX score_snapshot_date_index IF NOT EXISTS FOR (n:ScoreSnapshot) ON (n.as_of_date)",
]

# The vector index. The size (384) must equal config.EMBEDDING_DIMENSIONS, the size of one
# embedding. Neo4j does not allow a $parameter here, so the number is written in the text.
# A test checks that the two numbers are equal. The similarity is "cosine": two texts with the
# same meaning give a score near 1.
CHUNK_VECTOR_INDEX = (
    "CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS "
    "FOR (n:Chunk) ON (n.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}"
)

# The full-text index: it splits each chunk text into words, so a search for "stretching at home"
# finds the chunks that contain those words. The name must equal config.CHUNK_TEXT_INDEX_NAME.
CHUNK_TEXT_INDEX = "CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS FOR (n:Chunk) ON EACH [n.text]"


def create_graph_schema(driver: Driver) -> None:
    """Create all constraints and indexes. Safe to run many times."""
    all_statements = (
        UNIQUE_ID_CONSTRAINTS
        + [COMMUNITY_CONSTRAINT]
        + LOOKUP_INDEXES
        + [CHUNK_VECTOR_INDEX, CHUNK_TEXT_INDEX]
    )
    for statement in all_statements:
        driver.execute_query(statement)


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file", or:  .venv/bin/python -m src.data_loading.graph_schema
# Neo4j must be running. This is safe on a full graph: every statement is IF NOT EXISTS.
if __name__ == "__main__":
    from src.graph.connection import open_neo4j_driver

    driver = open_neo4j_driver()
    try:
        before, _, _ = driver.execute_query(
            "SHOW CONSTRAINTS YIELD name RETURN count(*) AS n"
        )
        print("Constraints before:", before[0]["n"])
        create_graph_schema(driver)
        after, _, _ = driver.execute_query(
            "SHOW CONSTRAINTS YIELD name RETURN count(*) AS n"
        )
        print(
            "Constraints after: ", after[0]["n"], "(the same number: nothing was added)"
        )
        print(
            f"The file holds {len(UNIQUE_ID_CONSTRAINTS)} constraints, {len(LOOKUP_INDEXES)} lookup indexes, 1 vector index."
        )
    finally:
        driver.close()
