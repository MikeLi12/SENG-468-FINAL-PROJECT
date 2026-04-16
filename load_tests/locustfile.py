

import io
import random
import string
import uuid
from pathlib import Path

from locust import HttpUser, task, between

SAMPLE_PDF_DIR = Path(__file__).parent.parent / "tests"
SAMPLE_PDFS = sorted(SAMPLE_PDF_DIR.glob("*.pdf"))

QUERIES = [
    "machine learning optimization techniques",
    "neural network training",
    "gradient descent convergence",
    "transformer architecture attention",
    "distributed systems consensus",
    "database indexing strategies",
    "vector embeddings semantic search",
    "asynchronous message processing",
]


def _rand_username():
    s = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"loadtest_{s}"


class BaseUser(HttpUser):
    abstract = True
    wait_time = between(0.5, 2.0)
    token = None

    def on_start(self):
        username, password = _rand_username(), "loadtest123"

        with self.client.post("/auth/signup",
                              json={"username": username, "password": password},
                              name="POST /auth/signup",
                              catch_response=True) as r:
            if r.status_code not in (200, 409):
                r.failure(f"signup {r.status_code}")
                return
            r.success()

        with self.client.post("/auth/login",
                              json={"username": username, "password": password},
                              name="POST /auth/login",
                              catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"login {r.status_code}")
                return
            self.token = r.json().get("token")
            r.success()

    def _hdr(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def do_upload(self):
        if not self.token or not SAMPLE_PDFS:
            return
        pdf_path = random.choice(SAMPLE_PDFS)
        unique_name = f"{uuid.uuid4().hex[:8]}_{pdf_path.name}"
        pdf_bytes = pdf_path.read_bytes()
        with self.client.post("/documents",
                              headers=self._hdr(),
                              files={"file": (unique_name, io.BytesIO(pdf_bytes), "application/pdf")},
                              name="POST /documents",
                              catch_response=True) as r:
            if r.status_code == 202:
                r.success()
            else:
                r.failure(f"upload {r.status_code}")

    def do_search(self):
        if not self.token:
            return
        q = random.choice(QUERIES)
        with self.client.get("/search",
                             params={"q": q},
                             headers=self._hdr(),
                             name="GET /search",
                             catch_response=True) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"search {r.status_code}")

    def do_list(self):
        if not self.token:
            return
        with self.client.get("/documents",
                             headers=self._hdr(),
                             name="GET /documents",
                             catch_response=True) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"list {r.status_code}")


class UploadUser(BaseUser):
    """Scenario 1: concurrent uploads."""
    weight = 1
    @task(5)
    def upload(self): self.do_upload()
    @task(1)
    def list_(self):  self.do_list()


class SearchUser(BaseUser):
    """Scenario 2: concurrent searches (each user uploads 1 PDF first)."""
    weight = 2
    def on_start(self):
        super().on_start()
        self.do_upload()
    @task(10)
    def search(self): self.do_search()
    @task(1)
    def list_(self):  self.do_list()


class MixedUser(BaseUser):
    """Scenario 3: mixed workload (the realistic case)."""
    weight = 3
    def on_start(self):
        super().on_start()
        self.do_upload()
    @task(3)
    def search(self): self.do_search()
    @task(1)
    def upload(self): self.do_upload()
    @task(1)
    def list_(self):  self.do_list()
