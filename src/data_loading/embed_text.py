"""Turn text into an embedding: a list of 384 numbers that stands for its meaning.

Texts with a similar meaning get similar lists. Example: "a car hit me from behind" and "I was rear-ended
at a light" score 0.53. "the weather is nice" scores 0.13.

The model is free and runs on this computer (sentence-transformers). No API key is needed. The first run
downloads the model (about 90 MB) into the Hugging Face cache of your home folder.
"""

from src import config

_model = None  # the model is loaded one time and reused


def get_model():
    """Load the model once. Loading takes about 10 seconds."""
    global _model
    if _model is None:
        # Imported here, so a file that never embeds does not wait for PyTorch to load.
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        if model.get_embedding_dimension() != config.EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"{config.EMBEDDING_MODEL_NAME} makes {model.get_embedding_dimension()} numbers, "
                f"but config.EMBEDDING_DIMENSIONS is {config.EMBEDDING_DIMENSIONS}."
            )
        _model = model
    return _model


def embed_texts(texts):
    """Return one embedding (a list of floats) for each text, in the same order."""
    if not texts:
        return []
    # normalize_embeddings=True makes every list length 1, so cosine similarity is a simple dot product.
    vectors = get_model().encode(
        texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False
    )
    return vectors.tolist()


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It needs no Neo4j.
if __name__ == "__main__":
    same_meaning = embed_texts(
        [
            "a car hit me from behind",
            "I was rear-ended at a light",
            "the weather is nice",
        ]
    )
    print("Each embedding has", len(same_meaning[0]), "numbers.")
    # Both lists have length 1, so the dot product is the cosine similarity.
    first, second, third = same_meaning
    print(
        "car hit me / rear-ended:", round(sum(a * b for a, b in zip(first, second)), 2)
    )
    print(
        "car hit me / weather:   ", round(sum(a * b for a, b in zip(first, third)), 2)
    )
