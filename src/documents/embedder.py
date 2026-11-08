"""Turn text into an embedding: a list of 384 numbers that stands for its meaning.

Texts with a similar meaning get similar lists. Example: "a car hit me from behind"
and "I was rear-ended at a light" score 0.53; "the weather is nice" scores 0.13.

The model is free and runs on this computer (sentence-transformers). The first run
downloads it (about 90 MB) to the Hugging Face cache in your home folder.
"""

import threading

from src import config

_model = None
_model_lock = threading.Lock()


def get_model():
    """Load the model once and reuse it. Loading takes about 10 seconds."""
    global _model
    with _model_lock:
        if _model is None:
            # Imported here, so commands that never embed do not wait for PyTorch to load.
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
            if model.get_embedding_dimension() != config.EMBEDDING_DIMENSIONS:
                raise RuntimeError(f"{config.EMBEDDING_MODEL_NAME} makes {model.get_embedding_dimension()} numbers, "
                                   f"but config.EMBEDDING_DIMENSIONS is {config.EMBEDDING_DIMENSIONS}.")
            _model = model
    return _model


def embed_texts(texts):
    """Return one embedding (a list of floats) for each text, in the same order."""
    if not texts:
        return []
    # normalize_embeddings=True makes every list length 1, so cosine similarity is a simple dot product.
    vectors = get_model().encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()
