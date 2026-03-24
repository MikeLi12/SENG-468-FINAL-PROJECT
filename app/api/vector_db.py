"""Qdrant vector database client for semantic search."""

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
)
import logging
from config import get_settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "document_chunks"

_client: QdrantClient | None = None


def get_qdrant() -> QdrantClient:
    global _client
    if _client is None:
        init_qdrant()
    return _client


def init_qdrant():
    global _client
    settings = get_settings()
    _client = QdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        timeout=30,
    )
    # Create collection if it doesn't exist
    collections = _client.get_collections().collections
    collection_names = [c.name for c in collections]

    if COLLECTION_NAME not in collection_names:
        _client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=settings.EMBEDDING_DIMENSION,
                distance=Distance.COSINE,
            ),
        )
        # Create payload index for filtering by user_id
        _client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="user_id",
            field_schema="keyword",
        )
        # Create payload index for filtering by document_id
        _client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="document_id",
            field_schema="keyword",
        )
        logger.info(f"Created Qdrant collection: {COLLECTION_NAME}")
    else:
        logger.info(f"Qdrant collection already exists: {COLLECTION_NAME}")


def search_vectors(query_embedding: list[float], user_id: str, top_k: int = 5) -> list[dict]:
    """Search for the top_k most similar vectors filtered by user_id."""
    client = get_qdrant()

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_embedding,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=user_id),
                )
            ]
        ),
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "text": hit.payload.get("text", ""),
            "score": round(hit.score, 4),
            "document_id": hit.payload.get("document_id", ""),
            "filename": hit.payload.get("filename", ""),
        }
        for hit in results
    ]


def delete_document_vectors(document_id: str):
    """Delete all vectors associated with a document."""
    client = get_qdrant()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=document_id),
                )
            ]
        ),
    )
    logger.info(f"Deleted vectors for document {document_id}")
