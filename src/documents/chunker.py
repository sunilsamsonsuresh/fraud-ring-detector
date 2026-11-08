"""Split page text into small overlapping pieces ("chunks") for the text search in Step 7.

A chunk never crosses a page, so every chunk has exactly one page number
(CLAUDE.md, rule 5.6: every fact from a PDF keeps its source).

Example with max_words=4 and overlap_words=1:
"a b c d e f g"  ->  "a b c d", "d e f g"
The overlap keeps a sentence that crosses a chunk border findable in both chunks.
"""

DEFAULT_MAX_WORDS = 150
DEFAULT_OVERLAP_WORDS = 30


def split_page_into_chunks(page_text, page_number, max_words=DEFAULT_MAX_WORDS,
                           overlap_words=DEFAULT_OVERLAP_WORDS):
    """Return [{"page_number", "chunk_number", "text"}, ...]. Empty text gives []."""
    if overlap_words >= max_words:
        raise ValueError("overlap_words must be smaller than max_words.")
    words = page_text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + max_words
        chunks.append({"page_number": page_number, "chunk_number": len(chunks) + 1,
                       "text": " ".join(words[start:end])})
        if end >= len(words):
            break
        start = end - overlap_words
    return chunks
