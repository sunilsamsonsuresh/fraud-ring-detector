"""Cut the text of a page into small overlapping pieces, called chunks.

Why: a search for "who was in the car" should return a short passage, not a whole page. Each chunk gets
an embedding (embed_text.py), and the embeddings make the search by meaning possible.

A chunk never crosses a page, so every chunk has exactly one page number (CLAUDE.md, rule 6).
The overlap keeps a sentence that crosses a chunk border findable in both chunks.

Example with max_words=4 and overlap_words=1:   "a b c d e f g"  ->  "a b c d", "d e f g"
"""

from src import config


def split_page_into_chunks(
    page_text,
    page_number,
    max_words=config.CHUNK_MAX_WORDS,
    overlap_words=config.CHUNK_OVERLAP_WORDS,
):
    """Return [{"page_number", "chunk_number", "text"}, ...]. Empty text gives []."""
    if overlap_words >= max_words:
        raise ValueError("overlap_words must be smaller than max_words.")
    words = page_text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + max_words
        chunks.append(
            {
                "page_number": page_number,
                "chunk_number": len(chunks) + 1,
                "text": " ".join(words[start:end]),
            }
        )
        if end >= len(words):
            break
        start = end - overlap_words
    return chunks


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    print(
        split_page_into_chunks(
            "a b c d e f g", page_number=1, max_words=4, overlap_words=1
        )
    )
