"""Step 4 of loading the graph: chunks with embeddings, for the search by meaning.

The flow, for each PDF:
1. read_pdf_pages.py reads the pages.
2. split_pages_into_chunks.py cuts each page into chunks.
3. embed_text.py gives each chunk an embedding (a list of 384 numbers).
4. This file saves each chunk as a Chunk node, linked to its Document (it must exist already).

No LLM and no cost: the embedding model runs on this computer.
Chunk ID example: "C-1037-fnol-p1-c2" = document C-1037-fnol, page 1, chunk 2.
Running it again updates the same chunks (MERGE), so there are no copies.
"""

from neo4j import Driver

from src import config
from src.data_loading import pdf_loading_queries as queries
from src.data_loading.embed_text import embed_texts
from src.data_loading.read_pdf_pages import read_pdf_pages
from src.data_loading.split_pages_into_chunks import split_page_into_chunks


def make_chunks(document_rows):
    """Read the PDFs of the rows and cut every page. Return (chunks without embeddings, warnings)."""
    chunks = []
    warnings = []
    for row in document_rows:
        try:
            pages = read_pdf_pages(config.PDFS_DIR / row["claim_id"] / row["file_name"])
        except (
            RuntimeError
        ) as problem:  # a missing or broken PDF: skip it, read the others
            warnings.append(str(problem))
            continue
        for page in pages:
            for chunk in split_page_into_chunks(page["text"], page["page_number"]):
                chunk["document_id"] = row["document_id"]
                chunk["chunk_id"] = (
                    f"{row['document_id']}-p{chunk['page_number']}-c{chunk['chunk_number']}"
                )
                chunks.append(chunk)
    return chunks, warnings


def load_chunks_into_graph(driver: Driver, document_rows):
    """Save the chunks of these PDFs. Return (number of chunks saved, warnings)."""
    chunks, warnings = make_chunks(document_rows)
    # One embedding call for all chunks: the model is much faster on a batch than on single texts.
    embeddings = embed_texts([chunk["text"] for chunk in chunks])
    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding
    driver.execute_query(queries.SAVE_CHUNKS, chunks=chunks)
    return len(chunks), warnings


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It reads and embeds the PDFs of ONE claim and shows the chunks.
# It writes nothing. It needs no Neo4j.
if __name__ == "__main__":
    from src.data_loading.load_documents_into_graph import (
        documents_of_claim,
        read_document_list,
    )

    chunks, warnings = make_chunks(documents_of_claim(read_document_list(), "C-1088"))
    print(len(chunks), "chunks for C-1088. Warnings:", warnings)
    for chunk in chunks[:3]:
        print(chunk["chunk_id"], "|", chunk["text"][:60], "...")
