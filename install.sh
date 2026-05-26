#!/bin/bash
# ===========================================================================
# IVMS Enterprise Single-Press VPS Installer System
# ===========================================================================
# Automatically provisions, bootstraps, and initializes the complete
# intelligent fleet infrastructure with a single execution.

echo "==========================================================================="
echo "                  IVMS ENTERPRISE PLATFORM INSTALLER                       "
echo "==========================================================================="

# 1. Run Host Bootstrap
echo "[1/5] Bootstrapping VPS Host limits & packages..."
chmod +x bootstrap.sh setup_ssl.sh init_database.sh healthcheck.sh verify-production.sh
./bootstrap.sh

if [ $? -ne 0 ]; then
    echo "[ERROR] Host bootstrap failed! Aborting installation."
    exit 1
fi

# 2. Setup TLS/SSL Security
echo "[2/5] Hardening SSL certificates and binding keys..."
./setup_ssl.sh

if [ $? -ne 0 ]; then
    echo "[ERROR] SSL setup failed!"
    exit 1
fi

# 3. Environment configuration template query
echo "[3/5] Syncing configuration parameters and generating secure credentials..."
if [ ! -f ".env" ]; then
    cp .env.template .env
    # Generate secure random secrets to prevent weak defaults in production
    sed -i "s/FLASK_SECRET=.*/FLASK_SECRET=$(openssl rand -hex 24)/" .env
    sed -i "s/ODOO_REPORT_TOKEN=.*/ODOO_REPORT_TOKEN=ivms_odoo_secure_token_$(date +%Y)/" .env
    echo "Generated secure keys in new .env file."
else
    echo "Existing .env file detected, preserving configs."
fi

# 4. Spin up microservices topology
echo "[4/5] Pulling and building Docker Compose containers..."
docker compose up -d --build

if [ $? -ne 0 ]; then
    echo "[ERROR] Container spin-up failed!"
    exit 1
fi

# 5. Initialize TimescaleDB schemas & data
echo "[5/5] Bootstrapping TimescaleDB schemas, tables, and partitions..."
./init_database.sh

# 6. Final verification & smoke test
echo "[$(date)] Running automated post-install health verification..."
sleep 5
./verify-production.sh

echo "==========================================================================="
echo "  [SUCCESS] IVMS Enterprise fleet infrastructure successfully deployed!     "
echo "  Primary Dashboard available at: https://72.61.254.210                     "
echo "  Prometheus Metrics route:       https://72.61.254.210/metrics             "
echo "==========================================================================="
