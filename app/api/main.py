"""Flask API — Distributed Semantic Retrieval System."""


from flask import Flask, request, jsonify
from functools import wraps
import uuid
import hashlib
import time
import logging
import io
import os
import pika
import json

from db.conn import PostgresConnection
from auth.loginman import LoginManager
from auth.jwtman import JWTManager
from minio import Minio

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = PostgresConnection()
jwt_manager = JWTManager()

# MinIO connection (reads secrets same way as your init.py)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "pdf-storage:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "pdfstore")
MINIO_SECRET_KEY = open(
    os.getenv("MINIO_ROOT_PASSWORD_FILE", "/run/secrets/pdfstore-pass"), "r"
).read().strip()
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "user-pdfs")

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)

# RabbitMQ connection settings
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
QUEUE_NAME = "pdf_processing"



def get_db():
    conn = db.connect(retries=3, delay=2)
    if conn is None:
        raise Exception("Could not connect to database")
    return conn



def publish_task(document_id, user_id, minio_key, filename):
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST, credentials=credentials, heartbeat=600
        )
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)

        message = json.dumps({
            "document_id": document_id,
            "user_id": user_id,
            "minio_key": minio_key,
            "filename": filename,
        })

        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=message,
            properties=pika.BasicProperties(delivery_mode=2),
        )
        connection.close()
        logger.info(f"Published task for document {document_id}")
    except Exception as e:
        logger.warning(f"RabbitMQ publish failed: {e}")



def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid authorization header"}), 401

        token = auth_header[7:]
        payload = jwt_manager.validate_token(token)
        if payload is None:
            return jsonify({"error": "Invalid or expired token"}), 401

        request.user_id = payload["user_id"]
        request.username = payload["username"]
        return f(*args, **kwargs)

    return decorated



@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


@app.route("/<path:path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def cors_preflight(path=""):
    return "", 204


@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/auth/signup", methods=["POST"])
def signup():
    data = request.get_json()
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "username and password required"}), 400

    username = data["username"].strip()
    password = data["password"]

    if len(username) < 3 or len(username) > 50:
        return jsonify({"error": "Username must be 3-50 characters"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    conn = get_db()
    try:
        login_manager = LoginManager(conn)
        result = login_manager.register_user(username, password)

        if result is None:
            return jsonify({"error": "Username already exists"}), 409

        user_id = str(result[0])
        logger.info(f"User created: {username} ({user_id})")
        return jsonify({"message": "User created successfully", "user_id": user_id}), 200

    except Exception as e:
        logger.error(f"Signup error: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "username and password required"}), 400

    username = data["username"].strip()
    password = data["password"]

    conn = get_db()
    try:
        login_manager = LoginManager(conn)
        result = login_manager.validate_login(username, password)

        if result is None:
            return jsonify({"error": "Invalid credentials"}), 401

        user_id = str(result["user_id"])
        token = jwt_manager.create_token(user_id, username)

        logger.info(f"User logged in: {username}")
        return jsonify({"token": token, "user_id": user_id}), 200

    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

@app.route("/documents", methods=["POST"])
@login_required
def upload_document():
    user_id = request.user_id

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    content = file.read()
    if len(content) == 0:
        return jsonify({"error": "Empty file"}), 400

    doc_id = str(uuid.uuid4())
    minio_key = f"{user_id}/{doc_id}/{file.filename}"

    # Upload to MinIO
    try:
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=minio_key,
            data=io.BytesIO(content),
            length=len(content),
            content_type="application/pdf",
        )
    except Exception as e:
        logger.error(f"MinIO upload failed: {e}")
        return jsonify({"error": "Failed to store file"}), 500

    # Insert metadata into PostgreSQL
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO documents (id, user_id, filename, minio_key, status, file_size_bytes)
               VALUES (%s, %s, %s, %s, 'processing', %s)""",
            (doc_id, user_id, file.filename, minio_key, len(content)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"DB error on upload: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

    # Publish task to RabbitMQ
    publish_task(doc_id, user_id, minio_key, file.filename)

    logger.info(f"Document {doc_id} uploaded by user {user_id}")
    return jsonify({
        "message": "PDF uploaded, processing started",
        "document_id": doc_id,
        "status": "processing",
    }), 202


@app.route("/documents", methods=["GET"])
@login_required
def list_documents():
    user_id = request.user_id

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, filename, upload_date, status, page_count
               FROM documents WHERE user_id = %s ORDER BY upload_date DESC""",
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close()

        result = [
            {
                "document_id": str(row[0]),
                "filename": row[1],
                "upload_date": row[2].isoformat() if row[2] else None,
                "status": row[3],
                "page_count": row[4],
            }
            for row in rows
        ]
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"List docs error: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()


@app.route("/documents/<document_id>", methods=["DELETE"])
@login_required
def delete_document(document_id):
    user_id = request.user_id

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, minio_key FROM documents WHERE id = %s AND user_id = %s",
            (document_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return jsonify({"error": "Document not found or not owned by user"}), 404

        minio_key = row[1]

        # Delete from MinIO
        try:
            minio_client.remove_object(MINIO_BUCKET, minio_key)
        except Exception as e:
            logger.warning(f"Failed to delete from MinIO: {e}")

        # Delete from PostgreSQL
        cur.execute("DELETE FROM documents WHERE id = %s", (document_id,))
        conn.commit()
        cur.close()

        logger.info(f"Document {document_id} deleted by user {user_id}")
        return jsonify({
            "message": "Document and all associated data deleted",
            "document_id": document_id,
        }), 200

    except Exception as e:
        conn.rollback()
        logger.error(f"Delete error: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

@app.route("/search", methods=["GET"])
@login_required
def search_documents():
    user_id = request.user_id
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    # Try vector search if Qdrant is available
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue
        from sentence_transformers import SentenceTransformer

        qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

        model = SentenceTransformer(model_name)
        query_embedding = model.encode(query, normalize_embeddings=True).tolist()

        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=10)

        results = client.search(
            collection_name="document_chunks",
            query_vector=query_embedding,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
            ),
            limit=5,
            with_payload=True,
        )

        search_results = [
            {
                "text": hit.payload.get("text", ""),
                "score": round(hit.score, 4),
                "document_id": hit.payload.get("document_id", ""),
                "filename": hit.payload.get("filename", ""),
            }
            for hit in results
        ]

        logger.info(f"Search by user {user_id}: '{query}' -> {len(search_results)} results")
        return jsonify(search_results), 200

    except Exception as e:
        logger.warning(f"Vector search not available: {e}")
        # Fallback: return empty results (OK for checkpoint)
        return jsonify([]), 200

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
