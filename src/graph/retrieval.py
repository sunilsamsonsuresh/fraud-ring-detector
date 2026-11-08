"""Text search over the PDF chunks (PLAN.md, A7 and Step 7).

GraphRAG in this project:
1. The graph says WHICH claims matter (Graph Investigator).
2. These functions compare text only inside the chunks of those claims.
3. Every result carries its source: claim, document, page.
"""

from src.documents.embedder import embed_texts
from src.graph import queries
from src.graph.schema import CHUNK_VECTOR_INDEX_NAME

# How many index results to fetch before removing the source's own document.
SIMILAR_CANDIDATES = 50


def search_text_in_claims(driver, question, claim_ids, limit=5):
    """The chunks of these claims that are closest in meaning to the question, best first."""
    if not claim_ids:
        return []
    question_embedding = embed_texts([question])[0]
    records, _, _ = driver.execute_query(queries.SEARCH_CHUNKS_IN_CLAIMS, claim_ids=list(claim_ids),
                                         embedding=question_embedding, limit=limit)
    return [dict(record) for record in records]


def find_copied_text(driver, claim_id, other_claim_ids, min_score, document_types):
    """Chunks of claim_id that are near-copies of chunks in the other claims (same document type)."""
    if not other_claim_ids:
        return []
    records, _, _ = driver.execute_query(queries.FIND_COPIED_TEXT, claim_id=claim_id,
                                         other_claim_ids=list(other_claim_ids), min_score=min_score,
                                         document_types=list(document_types))
    return [dict(record) for record in records]


def find_similar_chunks_anywhere(driver, chunk_id, limit=10):
    """The chunks in ALL other documents most similar to one chunk, using the vector index."""
    records, _, _ = driver.execute_query(queries.FIND_SIMILAR_CHUNKS_ANYWHERE, chunk_id=chunk_id,
                                         index_name=CHUNK_VECTOR_INDEX_NAME,
                                         candidate_count=SIMILAR_CANDIDATES, limit=limit)
    return [dict(record) for record in records]


def count_chunks_of_claims(driver, claim_ids):
    records, _, _ = driver.execute_query(queries.COUNT_CHUNKS_OF_CLAIMS, claim_ids=list(claim_ids))
    return records[0]["count"]
