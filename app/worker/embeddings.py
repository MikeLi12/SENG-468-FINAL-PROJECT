from sentence_transformers import SentenceTransformer
import os
import logging

logger = logging.getLogger(__name__)

_model = None
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

def get_model():
    global _model
    if _model is None:
        logger.info(f"Loading embedding model: {MODEL_NAME}")
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("Embedding model loaded successfully.")
    return _model

def generate_embeddings(texts, batch_size=32):
    model = get_model()
    embeddings = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
    logger.info(f"Generated {len(embeddings)} embeddings (dim={embeddings.shape[1]})")
    return embeddings.tolist()
