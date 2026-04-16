
RESULTS_DIR="$(dirname "$0")/results"

echo "============================================================"
echo "SENG 468 GROUP 15 — DATA FOR REPORT"
echo "Collected: $(date)"
echo "============================================================"

echo ""
echo "============================================================"
echo "SECTION A: HARDWARE SPECS"
echo "============================================================"
echo ""
echo "--- CPU ---"
lscpu | grep -E 'Model name|^CPU\(s\)|Thread|Core|MHz' 2>/dev/null || echo "lscpu not available"
echo ""
echo "--- RAM ---"
free -h 2>/dev/null || echo "free not available"
echo ""
echo "--- Disk ---"
df -h / 2>/dev/null || echo "df not available"
echo ""
echo "--- OS ---"
uname -a
echo ""
echo "--- Docker ---"
docker version --format 'Docker {{.Server.Version}}' 2>/dev/null || docker --version 2>/dev/null || echo "docker version not available"
echo ""
echo "--- Running containers ---"
docker compose ps 2>/dev/null || echo "not available"

echo ""
echo "============================================================"
echo "SECTION B: LOAD BALANCER VERIFICATION"
echo "============================================================"
for i in 1 2 3 4 5 6 7 8 9 10; do
    curl -s -I http://localhost:8080/health | grep X-Served-By &
done
wait
echo ""

echo ""
echo "============================================================"
echo "SECTION C: UPLOAD TEST RESULTS"
echo "============================================================"
if [ -f "$RESULTS_DIR/uploads_raw.csv" ]; then
    echo "Raw data (http_code,time_seconds):"
    cat "$RESULTS_DIR/uploads_raw.csv"
else
    echo "NOT FOUND — run load_tests/run_loadtest.sh first"
fi

echo ""
echo "============================================================"
echo "SECTION D: SEARCH TEST RESULTS"
echo "============================================================"
if [ -f "$RESULTS_DIR/searches_raw.csv" ]; then
    echo "Raw data (http_code,time_seconds):"
    cat "$RESULTS_DIR/searches_raw.csv"
else
    echo "NOT FOUND"
fi

echo ""
echo "============================================================"
echo "SECTION E: MIXED WORKLOAD RESULTS"
echo "============================================================"
if [ -f "$RESULTS_DIR/mixed_raw.csv" ]; then
    echo "Raw data (http_code,time_seconds):"
    cat "$RESULTS_DIR/mixed_raw.csv"
else
    echo "NOT FOUND"
fi

echo ""
echo "============================================================"
echo "SECTION F: SUSTAINED LOAD RESULTS (60s)"
echo "============================================================"
if [ -f "$RESULTS_DIR/sustained_raw.csv" ]; then
    echo "Raw data (http_code,time_seconds):"
    cat "$RESULTS_DIR/sustained_raw.csv"
else
    echo "NOT FOUND"
fi

echo ""
echo "============================================================"
echo "SECTION G: BREAKING POINT RESULTS"
echo "============================================================"
for CONCURRENT in 25 50 100 200; do
    f="$RESULTS_DIR/scale_${CONCURRENT}_raw.csv"
    echo ""
    echo "--- $CONCURRENT concurrent ---"
    if [ -f "$f" ]; then
        cat "$f"
    else
        echo "NOT RUN"
    fi
done

echo ""
echo "============================================================"
echo "SECTION H: DOCKER COMPOSE LOGS (last 30 lines per service)"
echo "============================================================"
for svc in nginx api1 api2 worker redis qdrant db rabbitmq; do
    echo ""
    echo "--- $svc ---"
    docker compose logs --tail=10 "$svc" 2>/dev/null || echo "not available"
done

echo ""
echo "============================================================"
echo "END OF REPORT DATA"
echo "============================================================"
