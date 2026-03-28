"""Embedding generation using sentence-transformers."""

from sentence_transformers import SentenceTransformer
import logging
from config import get_settings

logger = logging.getLogger(__name__)

_model = None


def get_model():
    global _model
    if _model is None:
        settings = get_settings()
        logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("Embedding model loaded successfully.")
    return _model


def generate_embeddings(texts, batch_size=32):
    """Generate normalized embeddings for a list of text chunks."""
    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    logger.info(f"Generated {len(embeddings)} embeddings (dim={embeddings.shape[1]})")
    return embeddings.tolist()
