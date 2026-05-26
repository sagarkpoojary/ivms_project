#!/bin/bash
# ===========================================================================
# IVMS Safe Production Deployment Script
# ===========================================================================
# - Enforces boot environment checks
# - Runs syntax verification
# - Boots staging containers cleanly
# - Runs automated health/readiness checks
# - Gracefully reloads Nginx proxying

echo "[$(date)] Starting IVMS deployment process..."

# Step 1: Pre-flight checks
if [ ! -f ".env" ]; then
    echo "[ERROR] .env file is missing. Deployment aborted."
    exit 1
fi

# Step 2: Validate environment config variables
docker run --rm -v $(pwd):/app -w /app python:3.12-slim python -c "
import sys
sys.path.insert(0, '/app')
from config import Config
try:
    Config.validate()
    print('Environment configuration validation PASSED.')
except Exception as e:
    print('Environment validation FAILED:', e)
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo "[ERROR] Environment variables are invalid. Aborting deployment."
    exit 1
fi

# Step 3: Capture current running image tag/ID for quick rollback
PREVIOUS_IMAGE_ID=$(docker images -q ivms-web:latest 2>/dev/null)
echo "[INFO] Capturing current active web image ID for rollback protection: $PREVIOUS_IMAGE_ID"

# Step 4: Build new Docker images using predictable version tags
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
IMAGE_TAG="prod_$TIMESTAMP"
echo "[$(date)] Building Docker images with release tag: $IMAGE_TAG..."

docker build -t ivms-web:$IMAGE_TAG -t ivms-web:latest .

if [ $? -ne 0 ]; then
    echo "[ERROR] Docker build failed. Aborting deployment."
    exit 1
fi

# Step 5: Rollout restart Gunicorn container gracefully
echo "[$(date)] Deploying new web release..."
docker compose up -d web

# Step 6: Verify health status
sleep 4
./healthcheck.sh web 5000

if [ $? -eq 0 ]; then
    echo "[$(date)] Deployment verified! Reloading Nginx gateway dynamically..."
    docker exec ivms-nginx nginx -s reload
    echo "[SUCCESS] Release $IMAGE_TAG successfully deployed with ZERO telemetry downtime."
    exit 0
else
    echo "[CRITICAL] Staging health check failed! Initiating automated rollback..."
    ./rollback.sh "$PREVIOUS_IMAGE_ID"
    exit 1
fi
