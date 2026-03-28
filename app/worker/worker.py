"""Background worker that consumes PDF processing tasks from RabbitMQ."""

import pika
import json
import uuid
import time
import logging
import os
import psycopg
from minio import Minio
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    PointStruct, Distance, VectorParams,
    Filter, FieldCondition, MatchValue,
)

from pdf_parser import extract_text_from_pdf, split_into_chunks
from embeddings import generate_embeddings

# ─── Config (reads secrets from files, same pattern as your other code) ──
WORKER_ID = os.getenv("WORKER_ID", "worker")

DB_HOST = "db"
DB_NAME = "userauth"
DB_USER = "userauth"
DB_PASSWORD = open("/run/secrets/userauth-pass").read().strip()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "pdf-storage:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "pdfstore")
MINIO_SECRET_KEY = open(
    os.getenv("MINIO_ROOT_PASSWORD_FILE", "/run/secrets/pdfstore-pass"), "r"
).read().strip()
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "user-pdfs")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "384"))

QUEUE_NAME = "pdf_processing"
COLLECTION_NAME = "document_chunks"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{WORKER_ID}] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

def get_postgres():
    return psycopg.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def get_minio_client():
    return Minio(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )


def get_qdrant_client():
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_DIMENSION,
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
        response = minio_client.get_object(MINIO_BUCKET, minio_key)
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
    try:
        task = json.loads(body)
        logger.info(f"Received task: document={task.get('document_id')}")
        process_document(task)
        channel.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        logger.error(f"Failed to process message: {e}", exc_info=True)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def main():
    logger.info(f"Worker {WORKER_ID} starting...")

    for attempt in range(30):
        try:
            credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
            params = pika.ConnectionParameters(
                host=RABBITMQ_HOST,
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

    logger.info(f"Worker {WORKER_ID} ready. Waiting for tasks...")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Worker shutting down...")
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
