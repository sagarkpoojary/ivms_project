#!/bin/bash
# ===========================================================================
# IVMS Automated Rollback Script
# ===========================================================================
# Restores the last active stable Docker container image immediately
# on health check or deployment failure.

PREVIOUS_IMAGE="$1"

if [ -z "$PREVIOUS_IMAGE" ]; then
    echo "[WARNING] No rollback target image ID provided. Reverting to backup image tags..."
    PREVIOUS_IMAGE="ivms-web:latest"
fi

echo "[$(date)] [ROLLBACK] Initiating system rollback to: $PREVIOUS_IMAGE..."

# Step 1: Re-tag target rollback image
docker tag "$PREVIOUS_IMAGE" ivms-web:latest

# Step 2: Restart web service
docker compose up -d web

# Step 3: Run sanity health checks
sleep 2
./healthcheck.sh web 5000

if [ $? -eq 0 ]; then
    echo "[$(date)] [ROLLBACK] Verification PASSED. Reloading Nginx to restore operations..."
    docker exec ivms-nginx nginx -s reload
    echo "[SUCCESS] Rollback completed. Fleet tracking is stable."
    exit 0
else
    echo "[FATAL] Rollback failed health verification! Operator intervention required."
    exit 1
fi
