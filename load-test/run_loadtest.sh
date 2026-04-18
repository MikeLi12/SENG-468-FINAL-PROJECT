
set -e

HOST="${HOST:-http://localhost:8080}"
RESULTS_DIR="$(dirname "$0")/results"
mkdir -p "$RESULTS_DIR"

# ── Colors ──────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# ── Helpers ─────────────────────────────────────────────────────
log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

# Time a curl request and return: http_code,time_total
timed_curl() {
    curl -s -o /dev/null -w '%{http_code},%{time_total}' "$@"
}

# Signup a user, return nothing (ignore if already exists)
signup_user() {
    local user="$1" pass="$2"
    curl -s -o /dev/null -X POST "$HOST/auth/signup" \
         -H 'Content-Type: application/json' \
         -d "{\"username\":\"$user\",\"password\":\"$pass\"}"
}

# Login a user, echo the token
login_user() {
    local user="$1" pass="$2"
    curl -s -X POST "$HOST/auth/login" \
         -H 'Content-Type: application/json' \
         -d "{\"username\":\"$user\",\"password\":\"$pass\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null
}

# Upload a PDF, return http_code,time_total
upload_pdf() {
    local token="$1" pdf="$2" unique_name="$3"
    timed_curl -X POST "$HOST/documents" \
               -H "Authorization: Bearer $token" \
               -F "file=@$pdf;filename=$unique_name"
}

# Search, return http_code,time_total
search_query() {
    local token="$1" query="$2"
    timed_curl "$HOST/search?q=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$query'))")" \
               -H "Authorization: Bearer $token"
}

# ── Stats calculator ────────────────────────────────────────────
calc_stats() {
    local label="$1" file="$2"
    python3 << PYEOF
import sys

times = []
codes = {}
with open("$file") as f:
    for line in f:
        line = line.strip()
        if not line: continue
        parts = line.split(",")
        if len(parts) != 2: continue
        code, t = parts[0], float(parts[1])
        times.append(t)
        codes[code] = codes.get(code, 0) + 1

if not times:
    print("  No data collected!")
    sys.exit(0)

times.sort()
n = len(times)
total = sum(times)
mean = total / n
p50  = times[int(n * 0.50)]
p90  = times[int(n * 0.90)]
p95  = times[int(n * 0.95)]
p99  = times[min(int(n * 0.99), n - 1)]
mn   = times[0]
mx   = times[-1]

ok = sum(v for k, v in codes.items() if k.startswith("2"))
fail = n - ok

print(f"  Requests:    {n}")
print(f"  Successes:   {ok}  (2xx)")
print(f"  Failures:    {fail}")
print(f"  Mean:        {mean*1000:.0f} ms")
print(f"  P50:         {p50*1000:.0f} ms")
print(f"  P90:         {p90*1000:.0f} ms")
print(f"  P95:         {p95*1000:.0f} ms")
print(f"  P99:         {p99*1000:.0f} ms")
print(f"  Min:         {mn*1000:.0f} ms")
print(f"  Max:         {mx*1000:.0f} ms")
print(f"  Throughput:  {n/total:.1f} req/s")
print(f"  Status codes: {codes}")
PYEOF
}

# ── Pre-flight check ────────────────────────────────────────────
log "Checking API health..."
if ! curl -sf "$HOST/health" > /dev/null; then
    err "API not reachable at $HOST/health"
    exit 1
fi
log "API is up."

# Pick a sample PDF
SAMPLE_PDF=""
for f in tests/sample*.pdf; do
    [ -f "$f" ] && SAMPLE_PDF="$f" && break
done
if [ -z "$SAMPLE_PDF" ]; then
    err "No sample PDFs found in tests/"
    exit 1
fi
log "Using sample PDF: $SAMPLE_PDF"

# ================================================================
# WARMUP PHASE (30 seconds)
# ================================================================
echo ""
echo "============================================================"
log "WARMUP: Priming caches, connections, and model (30 seconds)"
echo "============================================================"

# Create a warmup user
signup_user "warmup_user" "warmup123"
WARMUP_TOKEN=$(login_user "warmup_user" "warmup123")

# Upload a PDF so the worker loads its model and Qdrant collection exists
log "Uploading warmup PDF..."
curl -s -o /dev/null -X POST "$HOST/documents" \
     -H "Authorization: Bearer $WARMUP_TOKEN" \
     -F "file=@$SAMPLE_PDF;filename=warmup_$(date +%s).pdf"

log "Waiting 15s for worker to process warmup PDF..."
sleep 15

# Fire 20 search requests to warm up API model, Redis cache, Qdrant index
log "Firing 20 warmup search requests..."
for i in $(seq 1 20); do
    curl -s -o /dev/null "$HOST/search?q=warmup+test+query+$i" \
         -H "Authorization: Bearer $WARMUP_TOKEN" &
done
wait

# Fire 10 more health checks to warm up Nginx + Gunicorn workers
for i in $(seq 1 10); do
    curl -s -o /dev/null "$HOST/health" &
done
wait

log "Warmup complete. All caches and models are hot."
echo ""
sleep 2

# ================================================================
# BASELINE: Single-user sequential requests (no concurrency)
# ================================================================
echo ""
echo "============================================================"
log "BASELINE: Single-user sequential (20 requests, no concurrency)"
echo "============================================================"

BASELINE_RESULTS="$RESULTS_DIR/baseline_raw.csv"
> "$BASELINE_RESULTS"

log "Running 20 sequential search requests (single user, no parallelism)..."
for i in $(seq 1 20); do
    result=$(search_query "$WARMUP_TOKEN" "baseline test query")
    echo "$result" >> "$BASELINE_RESULTS"
done

log "Running 10 sequential upload requests (single user, no parallelism)..."
for i in $(seq 1 10); do
    unique="baseline_${i}_$(date +%s%N).pdf"
    result=$(upload_pdf "$WARMUP_TOKEN" "$SAMPLE_PDF" "$unique")
    echo "$result" >> "$BASELINE_RESULTS"
done

log "Baseline complete."

echo ""
echo "  --- Baseline Results (single user, sequential) ---"
calc_stats "Baseline" "$BASELINE_RESULTS"

# ================================================================
# SCENARIO 1: Concurrent Uploads (20 parallel users)
# ================================================================
echo ""
echo "============================================================"
log "SCENARIO 1: Concurrent Uploads (20 users, 3 uploads each)"
echo "============================================================"

UPLOAD_RESULTS="$RESULTS_DIR/uploads_raw.csv"
> "$UPLOAD_RESULTS"

# Create 20 users
TOKENS=()
for i in $(seq 1 20); do
    user="loadtest_upload_${i}"
    signup_user "$user" "loadtest123"
    token=$(login_user "$user" "loadtest123")
    TOKENS+=("$token")
done
log "20 users signed up and logged in."

# Fire 3 uploads per user (60 total) in parallel
log "Uploading 60 PDFs in parallel..."
for i in $(seq 1 20); do
    token="${TOKENS[$((i-1))]}"
    for j in 1 2 3; do
        unique="load_u${i}_${j}_$(date +%s%N).pdf"
        (
            result=$(upload_pdf "$token" "$SAMPLE_PDF" "$unique")
            echo "$result" >> "$UPLOAD_RESULTS"
        ) &
    done
done
wait
log "Upload scenario complete."

echo ""
echo "  --- Upload Results ---"
calc_stats "Uploads" "$UPLOAD_RESULTS"

# ================================================================
# SCENARIO 2: Concurrent Searches (50 parallel)
# ================================================================
echo ""
echo "============================================================"
log "SCENARIO 2: Concurrent Searches (50 parallel queries)"
echo "============================================================"

# Wait for some uploads to be processed
log "Waiting 20s for workers to process uploads..."
sleep 20

SEARCH_RESULTS="$RESULTS_DIR/searches_raw.csv"
> "$SEARCH_RESULTS"

QUERIES=(
    "machine learning optimization"
    "neural network training"
    "gradient descent convergence"
    "distributed systems consensus"
    "database indexing strategies"
    "vector embeddings semantic"
    "asynchronous message processing"
    "transformer architecture attention"
    "kubernetes container orchestration"
    "data preprocessing pipeline"
)

log "Firing 50 concurrent search requests..."
for i in $(seq 1 50); do
    token="${TOKENS[$(( (i-1) % 20 ))]}"
    query="${QUERIES[$(( (i-1) % ${#QUERIES[@]} ))]}"
    (
        result=$(search_query "$token" "$query")
        echo "$result" >> "$SEARCH_RESULTS"
    ) &
done
wait
log "Search scenario complete."

echo ""
echo "  --- Search Results ---"
calc_stats "Searches" "$SEARCH_RESULTS"

# ================================================================
# SCENARIO 3: Mixed Workload (uploads + searches simultaneously)
# ================================================================
echo ""
echo "============================================================"
log "SCENARIO 3: Mixed Workload (20 uploaders + 30 searchers)"
echo "============================================================"

MIXED_RESULTS="$RESULTS_DIR/mixed_raw.csv"
> "$MIXED_RESULTS"

# 20 uploaders (2 uploads each)
log "Firing mixed workload..."
for i in $(seq 1 20); do
    token="${TOKENS[$((i-1))]}"
    for j in 1 2; do
        unique="load_m${i}_${j}_$(date +%s%N).pdf"
        (
            result=$(upload_pdf "$token" "$SAMPLE_PDF" "$unique")
            echo "$result" >> "$MIXED_RESULTS"
        ) &
    done
done

# 30 searchers simultaneously
for i in $(seq 1 30); do
    token="${TOKENS[$(( (i-1) % 20 ))]}"
    query="${QUERIES[$(( (i-1) % ${#QUERIES[@]} ))]}"
    (
        result=$(search_query "$token" "$query")
        echo "$result" >> "$MIXED_RESULTS"
    ) &
done
wait
log "Mixed workload complete."

echo ""
echo "  --- Mixed Results ---"
calc_stats "Mixed" "$MIXED_RESULTS"

# ================================================================
# SCENARIO 4: Sustained load (60 seconds of continuous requests)
# ================================================================
echo ""
echo "============================================================"
log "SCENARIO 4: Sustained Load (60 seconds, 10 concurrent)"
echo "============================================================"

SUSTAINED_RESULTS="$RESULTS_DIR/sustained_raw.csv"
> "$SUSTAINED_RESULTS"

END_TIME=$(( $(date +%s) + 60 ))
REQUEST_COUNT=0

log "Running for 60 seconds with 10 concurrent workers..."
for w in $(seq 1 10); do
    (
        token="${TOKENS[$(( (w-1) % 20 ))]}"
        while [ "$(date +%s)" -lt "$END_TIME" ]; do
            query="${QUERIES[$(( RANDOM % ${#QUERIES[@]} ))]}"
            result=$(search_query "$token" "$query")
            echo "$result" >> "$SUSTAINED_RESULTS"
        done
    ) &
done
wait
log "Sustained load complete."

echo ""
echo "  --- Sustained Load Results ---"
calc_stats "Sustained" "$SUSTAINED_RESULTS"

# ================================================================
# SCENARIO 5: Breaking Point (ramp up concurrency)
# ================================================================
echo ""
echo "============================================================"
log "SCENARIO 5: Breaking Point (25, 50, 100, 200 concurrent)"
echo "============================================================"

for CONCURRENT in 25 50 100 200; do
    SCALE_RESULTS="$RESULTS_DIR/scale_${CONCURRENT}_raw.csv"
    > "$SCALE_RESULTS"

    log "Testing $CONCURRENT concurrent requests..."

    for i in $(seq 1 $CONCURRENT); do
        token="${TOKENS[$(( (i-1) % 20 ))]}"
        query="${QUERIES[$(( RANDOM % ${#QUERIES[@]} ))]}"
        (
            result=$(search_query "$token" "$query")
            echo "$result" >> "$SCALE_RESULTS"
        ) &
    done
    wait

    echo ""
    echo "  --- $CONCURRENT Concurrent ---"
    calc_stats "Scale_$CONCURRENT" "$SCALE_RESULTS"
done

# ================================================================
# SUMMARY
# ================================================================
echo ""
echo "============================================================"
echo "ALL SCENARIOS COMPLETE"
echo "============================================================"
echo ""
echo "Results saved to: $RESULTS_DIR/"
ls -la "$RESULTS_DIR"
echo ""
echo "To view any result:"
echo "  cat $RESULTS_DIR/uploads_raw.csv"
echo ""
log "Done!"
