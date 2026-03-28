"""Worker configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    POSTGRES_DB = os.getenv("POSTGRES_DB", "semantic_retrieval")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "sruser")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
    RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER = os.getenv("RABBITMQ_USER", "sruser")
    RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "changeme")

    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "changeme")
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "pdf-documents")
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

    QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "384"))

    WORKER_ID = os.getenv("WORKER_ID", "worker")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


_settings = None


def get_settings():
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
