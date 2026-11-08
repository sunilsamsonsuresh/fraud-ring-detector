"""Save every PDF page as Chunk nodes with embeddings (ingest-documents --chunks).

No LLM: the embedding model runs on this computer, so this costs nothing.
Chunk ID example: "C-1037-fnol-p1-c2" = document C-1037-fnol, page 1, chunk 2.
Running it again updates the same chunks (MERGE), so there are no copies.
"""

from src import config
from src.documents.chunker import split_page_into_chunks
from src.documents.embedder import embed_texts
from src.documents.pdf_reader import read_pdf_pages
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.graph.schema import create_schema


def make_chunks(document_rows):
    """Read the PDFs and split every page. Return (chunks, warnings)."""
    chunks = []
    warnings = []
    for row in document_rows:
        try:
            pages = read_pdf_pages(config.PDFS_DIR / row["claim_id"] / row["file_name"])
        except RuntimeError as problem:
            warnings.append(str(problem))
            continue
        for page in pages:
            for chunk in split_page_into_chunks(page["text"], page["page_number"]):
                chunk["document_id"] = row["document_id"]
                chunk["chunk_id"] = f"{row['document_id']}-p{chunk['page_number']}-c{chunk['chunk_number']}"
                chunks.append(chunk)
    return chunks, warnings


def store_chunks(claim_ids, document_rows):
    """Save Document and Chunk nodes for these claims. Return (number of chunks, warnings)."""
    rows_by_claim = {}
    for row in document_rows:
        rows_by_claim.setdefault(row["claim_id"], []).append(row)

    chunk_count = 0
    warnings = []
    driver = open_neo4j_driver()
    try:
        create_schema(driver)   # makes sure the vector index exists; does nothing if it does
        for number, claim_id in enumerate(claim_ids, start=1):
            rows = rows_by_claim.get(claim_id, [])
            chunks, claim_warnings = make_chunks(rows)
            warnings.extend(claim_warnings)
            # One embedding call per claim: the model is much faster on a batch than on single texts.
            embeddings = embed_texts([chunk["text"] for chunk in chunks])
            for chunk, embedding in zip(chunks, embeddings):
                chunk["embedding"] = embedding
            for row in rows:
                driver.execute_query(queries.SAVE_DOCUMENT, claim_id=claim_id, document_id=row["document_id"],
                                     document_type=row["document_type"], file_name=row["file_name"],
                                     page_count=int(row["page_count"]))
            driver.execute_query(queries.SAVE_CHUNKS, chunks=chunks)
            chunk_count += len(chunks)
            if number % 50 == 0 or number == len(claim_ids):
                print(f"  chunks: {number}/{len(claim_ids)} claims, {chunk_count} chunks so far")
    finally:
        driver.close()
    return chunk_count, warnings
