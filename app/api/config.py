"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # PostgreSQL
<<<<<<< HEAD
    POSTGRES_DB: str = "semantic_retrieval"
    POSTGRES_USER: str = "userauth"
    POSTGRES_PASSWORD: str = "userauth"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
=======
    POSTGRES_DB = os.getenv("POSTGRES_DB", "semantic_retrieval")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "sruser")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "changeme")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
>>>>>>> af77c01207854e9e46c37c29c47b6312ca495781

    # Redis
    REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "changeme")

    # RabbitMQ
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
    RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER = os.getenv("RABBITMQ_USER", "sruser")
    RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "changeme")

    # MinIO
    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "changeme")
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "pdf-documents")
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

    # Qdrant
    QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

    # JWT
    JWT_SECRET = os.getenv("JWT_SECRET", "changeme_jwt_secret")
    JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

    # Embedding
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "384"))

    # App
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    INSTANCE_ID = os.getenv("INSTANCE_ID", "api")


_settings = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
