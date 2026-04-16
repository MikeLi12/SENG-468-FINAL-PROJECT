import os
import time
from minio import Minio
from minio.error import S3Error


class MinioInitializer:
    def __init__(self):
        self.endpoint = os.getenv("MINIO_ENDPOINT", "pdf_storage:9000")
        self.access_key = os.getenv("MINIO_ROOT_USER", "pdfstore")
        self.secret_key = open(
            os.getenv("MINIO_ROOT_PASSWORD_FILE", "/run/secrets/pdfstore-pass"),
            "r",
        ).read().strip()
        self.bucket_name = os.getenv("MINIO_BUCKET", "user-pdfs")
        self.secure = False

    def get_client(self):
        print("connecting to MinIO db...")
        return Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )

    def ensure_bucket(self, retries=10, delay=3):
        for _ in range(retries):
            try:
                client = self.get_client()
                print("connected")
                print("checking for existing buckets...")
                if not client.bucket_exists(self.bucket_name):
                    client.make_bucket(self.bucket_name)
                    print(f"created bucket: {self.bucket_name}")
                else:
                    print(f"bucket already exists: {self.bucket_name}")

                return True

            except S3Error as e:
                print("minio bucket init failed:")
                print(e)
                time.sleep(delay)

            except Exception as e:
                print("minio connection failed:")
                print(e)
                time.sleep(delay)

        return False


if __name__ == "__main__":
    ok = MinioInitializer().ensure_bucket()
    if not ok:
        raise SystemExit(1)
