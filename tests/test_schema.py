"""Step 1 tests: the schema exists in Neo4j and the setup can run twice.

Neo4j must be running (docker compose up -d).
"""

from src import config
from src.graph.connection import open_neo4j_driver
from src.graph.schema import CHUNK_VECTOR_INDEX_NAME, create_schema

EXPECTED_CONSTRAINT_NAMES = [
    "claimant_id_unique", "claim_id_unique", "policy_id_unique",
    "vehicle_id_unique", "address_id_unique", "phone_number_unique",
    "provider_id_unique", "attorney_id_unique", "law_firm_id_unique",
    "lawsuit_id_unique", "court_id_unique", "expert_id_unique",
    "payment_id_unique", "document_id_unique", "chunk_id_unique",
]

EXPECTED_LOOKUP_INDEX_NAMES = [
    "claimant_name_index", "claimant_birth_date_index", "provider_name_index",
    "attorney_name_index", "law_firm_name_index", "expert_name_index",
]


def test_schema_can_run_twice_and_everything_exists():
    driver = open_neo4j_driver()
    try:
        # Running twice is the point: the second run must not raise an error.
        create_schema(driver)
        create_schema(driver)

        constraint_records, _, _ = driver.execute_query("SHOW CONSTRAINTS YIELD name")
        index_records, _, _ = driver.execute_query("SHOW INDEXES YIELD name, type, options")
    finally:
        driver.close()

    constraint_names = [record["name"] for record in constraint_records]
    for expected_name in EXPECTED_CONSTRAINT_NAMES:
        assert expected_name in constraint_names, f"Missing constraint: {expected_name}"

    index_by_name = {}
    for record in index_records:
        index_by_name[record["name"]] = record

    for expected_name in EXPECTED_LOOKUP_INDEX_NAMES:
        assert expected_name in index_by_name, f"Missing index: {expected_name}"

    vector_index = index_by_name[CHUNK_VECTOR_INDEX_NAME]
    assert vector_index["type"] == "VECTOR"
    vector_settings = vector_index["options"]["indexConfig"]
    assert vector_settings["vector.dimensions"] == config.EMBEDDING_DIMENSIONS
    assert vector_settings["vector.similarity_function"].upper() == "COSINE"
