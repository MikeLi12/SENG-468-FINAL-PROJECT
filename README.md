# SENG 468 — Distributed Semantic Retrieval System (Group 15)

A scalable semantic search engine: users upload PDFs, then search them
with natural-language queries that hit dense vector embeddings.

## Quick Start

```bash
git clone <your-repo-url>
cd SENG-468-FINAL-PROJECT
cp .env.example .env
docker compose up --build
```

API is on **`http://localhost:8080`**.

## Architecture

| Component   | Role                                          |
|-------------|-----------------------------------------------|
| Nginx       | Load balancer (port 8080, round-robin)        |
| Flask API   | HTTP endpoints, ×2 instances behind Nginx     |
| RabbitMQ    | Async PDF-processing queue                    |
| Worker      | PDF parse → chunk → embed                     |
| MinIO       | Object storage for PDFs                       |
| PostgreSQL  | User accounts (with connection pool)          |
| Qdrant      | Vector DB (cosine, HNSW, per-user filter)     |
| Redis       | Query-embedding cache (LRU, 256 MB)           |

```
Client → Nginx ─┬─→ api1 ─┐
       :8080    └─→ api2 ─┤
                          ├→ MinIO (store PDF)
                          ├→ Postgres (auth)
                          ├→ Qdrant (search)
                          ├→ Redis (cache)
                          └→ RabbitMQ → Worker → Qdrant (embed)
```

## API (port 8080)

| Method | Path                    | Auth | Notes                              |
|--------|-------------------------|------|------------------------------------|
| POST   | `/auth/signup`          | no   | `{username, password}`             |
| POST   | `/auth/login`           | no   | returns JWT                        |
| POST   | `/documents`            | yes  | multipart `file=<pdf>`, returns 202|
| GET    | `/documents`            | yes  | list user's docs                   |
| DELETE | `/documents/{id}`       | yes  | removes file + vectors             |
| GET    | `/search?q=<query>`     | yes  | top 5 chunks                       |
| GET    | `/health`               | no   | liveness                           |

Auth header: `Authorization: Bearer <token>`

## Smoke Test

```bash
curl http://localhost:8080/health

curl -X POST http://localhost:8080/auth/signup \
     -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"securepw"}'

TOKEN=$(curl -s -X POST http://localhost:8080/auth/login \
        -H 'Content-Type: application/json' \
        -d '{"username":"alice","password":"securepw"}' | jq -r .token)

curl -X POST http://localhost:8080/documents \
     -H "Authorization: Bearer $TOKEN" \
     -F "file=@tests/sample1.pdf"

curl "http://localhost:8080/search?q=test" \
     -H "Authorization: Bearer $TOKEN"
```

## Load Tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install locust==2.20.0
locust -f load_tests/locustfile.py --host=http://localhost:8080
```

## Configuration

All settings have sensible defaults baked into `docker-compose.yml`. See
`.env.example` for what can be overridden.

## Repo Layout

```
.
├── docker-compose.yml
├── .env.example
├── README.md
├── REPORT.pdf
├── app/
│   ├── api/            Flask API (entrypoint: main.py)
│   ├── worker/         RabbitMQ consumer + embedder
│   ├── auth/           JWT + login
│   ├── db/             Postgres helper
│   ├── user-auth-init/ DB schema bootstrap
│   └── pdf-stor-init/  MinIO bucket bootstrap
├── load_tests/         Locust scripts
├── tests/              Sample PDFs
└── secrets/            Local dev secrets (rotate for prod)
```
