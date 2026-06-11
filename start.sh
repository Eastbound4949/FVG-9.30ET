#!/bin/bash
set -e

echo "=== FVG 9:30 ET ORB Bot Starting ==="
echo "Starting Streamlit dashboard on :8502 (internal only)..."
streamlit run main.py \
    --server.port 8502 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false &
DASH_PID=$!
echo "Dashboard started (PID $DASH_PID)"

echo "Starting scheduler worker (binds \$PORT for /signal + /health)..."
exec python -u worker.py
