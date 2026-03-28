"""Background worker that consumes PDF processing tasks from RabbitMQ.

Pipeline per task:
1. Download PDF from MinIO
2. Extract text (PyMuPDF)
3. Split into chunks (paragraph-based)
4. Generate embeddings (sentence-transformers)
5. Store vectors in Qdrant
6. Update document status in PostgreSQL
"""

import pika
import json
import uuid
import time
import logging
import psycopg2
from minio import Minio
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    PointStruct, Distance, VectorParams,
    Filter, FieldCondition, MatchValue,
)

from config import get_settings
from pdf_parser import extract_text_from_pdf, split_into_chunks
from embeddings import generate_embeddings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format=f"%(asctime)s [{settings.WORKER_ID}] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

QUEUE_NAME = "pdf_processing"
COLLECTION_NAME = "document_chunks"


def get_postgres():
    return psycopg2.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname=settings.POSTGRES_DB,
    )


def get_minio_client():
    return Minio(
        endpoint=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def get_qdrant_client():
    client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=60)
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=settings.EMBEDDING_DIMENSION,
                distance=Distance.COSINE,
            ),
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME, field_name="user_id", field_schema="keyword"
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME, field_name="document_id", field_schema="keyword"
        )
    return client


def process_document(task):
    """Full processing pipeline for a single document."""
    doc_id = task["document_id"]
    user_id = task["user_id"]
    minio_key = task["minio_key"]
    filename = task["filename"]

    start_time = time.time()
    logger.info(f"Processing document {doc_id} ({filename})")

    pg = get_postgres()
    try:
        # 1. Download PDF from MinIO
        minio_client = get_minio_client()
        response = minio_client.get_object(settings.MINIO_BUCKET, minio_key)
        pdf_bytes = response.read()
        response.close()
        response.release_conn()
        logger.info(f"  Downloaded {len(pdf_bytes)} bytes from MinIO")

        # 2. Extract text
        full_text, page_count = extract_text_from_pdf(pdf_bytes)
        if not full_text.strip():
            _update_status(pg, doc_id, "error", page_count=page_count,
                          error="No extractable text found in PDF")
            return

        # 3. Split into chunks
        chunks = split_into_chunks(full_text)
        if not chunks:
            _update_status(pg, doc_id, "error", page_count=page_count,
                          error="No valid chunks after splitting")
            return

        logger.info(f"  {len(chunks)} chunks from {page_count} pages")

        # 4. Generate embeddings
        embeddings = generate_embeddings(chunks)

        # 5. Store in Qdrant
        qdrant = get_qdrant_client()
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=emb,
                payload={
                    "text": chunk,
                    "document_id": doc_id,
                    "user_id": user_id,
                    "filename": filename,
                    "chunk_index": i,
                },
            )
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]

        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            qdrant.upsert(collection_name=COLLECTION_NAME, points=batch)
            logger.info(f"  Upserted batch {i // batch_size + 1} ({len(batch)} points)")

        # 6. Update status to ready
        _update_status(pg, doc_id, "ready", page_count=page_count, chunk_count=len(chunks))

        elapsed = time.time() - start_time
        logger.info(f"  Document {doc_id} processed in {elapsed:.1f}s "
                     f"({page_count} pages, {len(chunks)} chunks)")

    except Exception as e:
        logger.error(f"  Error processing document {doc_id}: {e}", exc_info=True)
        try:
            _update_status(pg, doc_id, "error", error=str(e)[:500])
        except Exception:
            pass
    finally:
        pg.close()


def _update_status(pg, doc_id, status, page_count=None, chunk_count=None, error=None):
    """Update document processing status in PostgreSQL."""
    cur = pg.cursor()
    cur.execute(
        """UPDATE documents
           SET status = %s, page_count = COALESCE(%s, page_count),
               chunk_count = COALESCE(%s, chunk_count),
               error_message = %s,
               processed_at = NOW()
           WHERE id = %s""",
        (status, page_count, chunk_count, error, doc_id),
    )
    pg.commit()
    cur.close()


def on_message(channel, method, properties, body):
    """Callback for processing a RabbitMQ message."""
    try:
        task = json.loads(body)
        logger.info(f"Received task: document={task.get('document_id')}")
        process_document(task)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.error(f"Failed to process message: {e}", exc_info=True)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def main():
    logger.info(f"Worker {settings.WORKER_ID} starting...")

    for attempt in range(30):
        try:
            credentials = pika.PlainCredentials(settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD)
            params = pika.ConnectionParameters(
                host=settings.RABBITMQ_HOST,
                port=settings.RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
            connection = pika.BlockingConnection(params)
            break
        except Exception as e:
            logger.warning(f"RabbitMQ not ready (attempt {attempt + 1}/30): {e}")
            time.sleep(2)
    else:
        logger.error("Could not connect to RabbitMQ after 30 attempts")
        return

    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)

    logger.info(f"Worker {settings.WORKER_ID} ready. Waiting for tasks...")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Worker shutting down...")
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
