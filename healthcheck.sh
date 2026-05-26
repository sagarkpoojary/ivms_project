#!/bin/bash
# ===========================================================================
# IVMS Container Liveness & Readiness Verification Probes
# ===========================================================================

CONTAINER_NAME="$1"
PORT="$2"

if [ -z "$CONTAINER_NAME" ] || [ -z "$PORT" ]; then
    echo "Usage: $0 <container_name> <port>"
    exit 1
fi

echo "[$(date)] Probing readiness on $CONTAINER_NAME:$PORT..."

# Extract container IP Address inside Docker bridge network
CONTAINER_IP=$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "ivms-$CONTAINER_NAME")

if [ -z "$CONTAINER_IP" ]; then
    # Fallback to localhost if inspect fails
    CONTAINER_IP="localhost"
fi

# Hit health check route
LIVENESS_URL="http://${CONTAINER_IP}:${PORT}/health"
READINESS_URL="http://${CONTAINER_IP}:${PORT}/ready"

# Attempt up to 5 times
MAX_RETRIES=5
RETRY_DELAY=2

for ((i=1; i<=MAX_RETRIES; i++)); do
    echo "[Attempt $i/$MAX_RETRIES] Pinging liveness probe at $LIVENESS_URL..."
    HTTP_STATUS=$(docker exec ivms-nginx curl -s -o /dev/null -w "%{http_code}" "$LIVENESS_URL")
    
    if [ "$HTTP_STATUS" -eq 200 ]; then
        echo "[SUCCESS] Container liveness check PASSED."
        
        # Test readiness (DB online, caches accessible)
        echo "Pinging readiness probe at $READINESS_URL..."
        READY_STATUS=$(docker exec ivms-nginx curl -s -o /dev/null -w "%{http_code}" "$READINESS_URL")
        
        if [ "$READY_STATUS" -eq 200 ]; then
            echo "[SUCCESS] Container readiness check PASSED. Boot completed cleanly."
            exit 0
        else
            echo "[WARNING] Liveness OK, but readiness probe returned HTTP $READY_STATUS."
        fi
    else
        echo "[WARNING] Liveness probe returned HTTP $HTTP_STATUS."
    fi
    
    sleep $RETRY_DELAY
done

echo "[ERROR] Health check verification FAILED after $MAX_RETRIES attempts!"
exit 1
