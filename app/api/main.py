from flask import Flask, request, jsonify
from functools import wraps
from datetime import datetime, timezone
import uuid
import logging
import io
import os
import json
import pika

from auth.loginman import LoginManager
from auth.jwtman import JWTManager
from db.conn import PostgresConnection
from psycopg_pool import ConnectionPool
from minio import Minio
from minio.error import S3Error

# ── Loaded ONCE at module import (was previously per-request inside /search) ──
from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from sentence_transformers import SentenceTransformer
import hashlib
import redis as redis_lib

_QDRANT_HOST  = os.getenv("QDRANT_HOST", "qdrant")
_QDRANT_PORT  = int(os.getenv("QDRANT_PORT", "6333"))
_MODEL_NAME   = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
_REDIS_HOST   = os.getenv("REDIS_HOST", "redis")
_REDIS_PORT   = int(os.getenv("REDIS_PORT", "6379"))
_CACHE_TTL    = int(os.getenv("CACHE_TTL", "300"))

_embedding_model  = SentenceTransformer(_MODEL_NAME)
_qdrant_singleton = QdrantClient(host=_QDRANT_HOST, port=_QDRANT_PORT, timeout=10)

# Redis cache for query embeddings — degrades gracefully if Redis is down
try:
    _redis_cache = redis_lib.Redis(
        host=_REDIS_HOST, port=_REDIS_PORT,
        socket_timeout=2, socket_connect_timeout=2,
        decode_responses=False,
    )
    _redis_cache.ping()
except Exception:
    _redis_cache = None


def embed_query_cached(query):
    """Return (vector, cache_hit_bool). Falls back to direct embedding if
    Redis is unavailable."""
    if _redis_cache is None:
        return _embedding_model.encode(query, normalize_embeddings=True).tolist(), False
    key = b"q:" + hashlib.sha256(query.encode("utf-8")).digest()
    try:
        cached = _redis_cache.get(key)
        if cached is not None:
            return json.loads(cached), True
    except Exception:
        pass
    vec = _embedding_model.encode(query, normalize_embeddings=True).tolist()
    try:
        _redis_cache.setex(key, _CACHE_TTL, json.dumps(vec))
    except Exception:
        pass
    return vec, False

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = PostgresConnection()
jwt_manager = JWTManager()

# Postgres connection pool (was: a fresh TCP connection per request)
_pg_pool = ConnectionPool(
    conninfo=(
        f"host={db.host} dbname={db.dbname} "
        f"user={db.user} password={db.password}"
    ),
    min_size=2,
    max_size=10,
    timeout=10,
)

# MinIO connection
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
    """Check out a connection from the pool. Caller must return it via
    _pg_pool.putconn(conn) when done."""
    conn = _pg_pool.getconn(timeout=10)
    if conn is None:
        raise Exception("Could not obtain database connection from pool")
    return conn


def publish_task(document_id, user_id, minio_key, filename):
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            credentials=credentials,
            heartbeat=600,
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
        logger.info("Published task for document %s", document_id)

    except Exception as e:
        logger.warning("RabbitMQ publish failed: %s", e)


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


def get_document_status(user_id, document_id):
    """Return ('ready', chunk_count) if Qdrant has chunks for this doc,
    otherwise ('processing', 0). Used by GET /documents."""
    try:
        cnt = _qdrant_singleton.count(
            collection_name="document_chunks",
            count_filter=Filter(must=[
                FieldCondition(key="user_id",     match=MatchValue(value=user_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]),
            exact=False,
        ).count
        return ("ready", cnt) if cnt > 0 else ("processing", 0)
    except Exception:
        return ("processing", 0)


def extract_document_info(object_name, last_modified=None):
    """
    Expected object key format:
    <user_id>/<document_id>/<filename>
    """
    parts = object_name.split("/", 2)
    if len(parts) != 3:
        return None

    user_id, document_id, filename = parts

    upload_date = None
    if last_modified is not None:
        if isinstance(last_modified, datetime):
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            upload_date = last_modified.isoformat()

    return {
        "user_id": user_id,
        "document_id": document_id,
        "filename": filename,
        "upload_date": upload_date,
        # Since metadata is no longer stored in Postgres, keep these minimal
        "status": "uploaded",
        "page_count": None,
    }


def find_user_document_object(user_id, document_id):
    """
    Find a single object belonging to a given user/document_id.
    Returns the full MinIO object key if found, else None.
    """
    prefix = f"{user_id}/{document_id}/"

    for obj in minio_client.list_objects(
        MINIO_BUCKET,
        prefix=prefix,
        recursive=True,
    ):
        return obj.object_name

    return None


@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["X-Served-By"] = os.getenv("INSTANCE_ID", "api")
    return response


@app.route("/<path:path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def cors_preflight(path=""):
    return "", 204


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


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
        logger.info("User created: %s (%s)", username, user_id)
        return jsonify({
            "message": "User created successfully",
            "user_id": user_id,
        }), 200

    except Exception as e:
        logger.error("Signup error: %s", e)
        return jsonify({"error": "Internal server error"}), 500
    finally:
        _pg_pool.putconn(conn)


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

        logger.info("User logged in: %s", username)
        return jsonify({"token": token, "user_id": user_id}), 200

    except Exception as e:
        logger.error("Login error: %s", e)
        return jsonify({"error": "Internal server error"}), 500
    finally:
        _pg_pool.putconn(conn)


@app.route("/documents", methods=["POST"])
@login_required
def upload_document():
    user_id = request.user_id

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Missing filename"}), 400

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    # duplicate filename check per user
    try:
        if user_already_has_filename(user_id, file.filename):
            return jsonify({
                "error": "A document with this filename already exists"
            }), 409
    except Exception as e:
        logger.error("Duplicate filename check failed: %s", e)
        return jsonify({"error": "Internal server error"}), 500

    content = file.read()
    if not content:
        return jsonify({"error": "Empty file"}), 400

    document_id = str(uuid.uuid4())
    minio_key = f"{user_id}/{document_id}/{file.filename}"

    try:
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=minio_key,
            data=io.BytesIO(content),
            length=len(content),
            content_type="application/pdf",
        )
    except Exception as e:
        logger.error("MinIO upload failed: %s", e)
        return jsonify({"error": "Failed to store file"}), 500

    publish_task(document_id, user_id, minio_key, file.filename)

    logger.info("Document %s uploaded by user %s", document_id, user_id)
    return jsonify({
        "message": "PDF uploaded, processing started",
        "document_id": document_id,
        "status": "processing",
    }), 202


@app.route("/documents", methods=["GET"])
@login_required
def list_documents():
    user_id = request.user_id
    prefix = f"{user_id}/"

    try:
        documents = []

        for obj in minio_client.list_objects(
            MINIO_BUCKET,
            prefix=prefix,
            recursive=True,
        ):
            info = extract_document_info(
                object_name=obj.object_name,
                last_modified=obj.last_modified,
            )
            if info is None:
                continue

            # Real status from Qdrant (was hardcoded "uploaded" before)
            status, chunk_count = get_document_status(user_id, info["document_id"])

            documents.append({
                "document_id": info["document_id"],
                "filename": info["filename"],
                "upload_date": info["upload_date"],
                "status": status,
                "page_count": chunk_count if status == "ready" else None,
            })

        documents.sort(
            key=lambda d: d["upload_date"] or "",
            reverse=True,
        )

        return jsonify(documents), 200

    except Exception as e:
        logger.error("List docs error: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/documents/<document_id>", methods=["DELETE"])
@login_required
def delete_document(document_id):
    user_id = request.user_id

    try:
        object_name = find_user_document_object(user_id, document_id)
        if object_name is None:
            return jsonify({
                "error": "Document not found or not owned by user"
            }), 404

        minio_client.remove_object(MINIO_BUCKET, object_name)

        # Also remove all chunks for this document from Qdrant (spec: delete
        # "removes file and all vector data")
        try:
            from qdrant_client.http.models import FilterSelector
            _qdrant_singleton.delete(
                collection_name="document_chunks",
                points_selector=FilterSelector(
                    filter=Filter(must=[
                        FieldCondition(key="user_id",     match=MatchValue(value=user_id)),
                        FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                    ])
                ),
            )
        except Exception as e:
            logger.warning("Qdrant cleanup failed for %s: %s", document_id, e)

        logger.info("Document %s deleted by user %s", document_id, user_id)
        return jsonify({
            "message": "Document and all associated data deleted",
            "document_id": document_id,
        }), 200

    except Exception as e:
        logger.error("Delete error: %s", e)
        return jsonify({"error": "Internal server error"}), 500


@app.route("/search", methods=["GET"])
@login_required
def search_documents():
    user_id = request.user_id
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    try:
        # Use the module-level singletons (huge perf fix — was loading 80MB
        # model on every request before). Redis caches repeated query embeddings.
        query_embedding, cache_hit = embed_query_cached(query)

        results = _qdrant_singleton.search(
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

        logger.info(
            "Search by user %s: '%s' -> %s results (cache_hit=%s)",
            user_id,
            query,
            len(search_results),
            cache_hit,
        )
        return jsonify(search_results), 200

    except Exception as e:
        logger.warning("Vector search not available: %s", e)
        return jsonify([]), 200

def get_filename_from_object_key(object_name):
    """
    Expected key format:
    <user_id>/<document_id>/<filename>
    """
    parts = object_name.split("/", 2)
    if len(parts) != 3:
        return None
    return parts[2]


def user_already_has_filename(user_id, filename):
    """
    Return True if this user already has a document with the same filename.
    """
    prefix = f"{user_id}/"

    for obj in minio_client.list_objects(
        MINIO_BUCKET,
        prefix=prefix,
        recursive=True,
    ):
        existing_filename = get_filename_from_object_key(obj.object_name)
        if existing_filename == filename:
            return True

    return False

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
