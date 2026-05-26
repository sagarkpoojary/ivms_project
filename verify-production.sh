#!/bin/bash
# ===========================================================================
# IVMS Enterprise Production Audit & Verification Dashboard Script
# ===========================================================================
# Conducts a full status audit of active system components:
# 1. Disk usage parameters
# 2. SSL certificate expiry countdowns
# 3. Redis live state responsiveness
# 4. TimescaleDB replication latency
# 5. Teltonika active socket bindings

echo "==========================================================================="
echo "                  IVMS ENTERPRISE SYSTEM HEALTH STATUS                      "
echo "==========================================================================="
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S UTC")
echo "Audit Timestamp: $TIMESTAMP"
echo "---------------------------------------------------------------------------"

# 1. Disk usage monitor
echo -n "Disk Space Verification: "
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 85 ]; then
    echo "[OK] Root volume usage is safe ($DISK_USAGE%)."
else
    echo "[ALERT] Disk space is critically low ($DISK_USAGE%)!"
fi

# 2. SSL Certificate expiry countdown
echo -n "SSL Certificate Status:  "
SSL_EXPIRY_DATE=$(openssl x509 -enddate -noout -in /root/ivms_project/nginx/ssl/server.crt | cut -d= -f2)
SSL_EXPIRY_EPOCH=$(date -d "$SSL_EXPIRY_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (SSL_EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -gt 30 ]; then
    echo "[OK] Certificate is valid ($DAYS_LEFT days remaining)."
else
    echo "[WARNING] SSL certificate expires soon in $DAYS_LEFT days! Renew immediately."
fi

# 3. Redis health test
echo -n "Redis Status:            "
REDIS_PING=$(docker exec ivms-redis redis-cli ping 2>/dev/null)
if [ "$REDIS_PING" = "PONG" ]; then
    echo "[OK] Cache responsive."
else
    echo "[CRITICAL] Redis is fully unresponsive!"
fi

# 4. TimescaleDB check
echo -n "TimescaleDB Status:      "
DB_REPLY=$(docker exec ivms-db pg_isready -U ivmsuser -d ivmsdb 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "[OK] Primary PostgreSQL active and listening."
else
    echo "[CRITICAL] Database service is down!"
fi

# 5. Ingestion Port TCP check
echo -n "Teltonika Port (5027):   "
docker exec ivms-nginx nc -zv ingestion 5027 2>/dev/null
if [ $? -eq 0 ]; then
    echo "[OK] TCP Ingestion listening on 5027."
else
    echo "[CRITICAL] Ingestion service socket offline!"
fi

# 6. Active Device count from Redis live status
echo -n "Live Active Devices:     "
LIVE_COUNT=$(docker exec ivms-redis redis-cli keys "live_status:*" | wc -l)
echo "$LIVE_COUNT devices currently cached."
echo "==========================================================================="
