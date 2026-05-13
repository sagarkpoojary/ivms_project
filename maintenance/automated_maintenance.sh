#!/bin/bash
# Enterprise IVMS - Automated Maintenance Script

BACKUP_DIR="/root/ivms_project/artifacts/backups"
DB_NAME=${DB_NAME:-ivmsdb}
DB_USER=${DB_USER:-ivmsuser}
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

echo "--- Starting Maintenance: $DATE ---"

# 1. Database Backup (Logical)
echo "Backing up database: $DB_NAME..."
docker exec ivms_project-db-1 pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/${DB_NAME}_${DATE}.sql.gz
echo "Backup saved: ${DB_NAME}_${DATE}.sql.gz"

# 2. Cleanup Old Backups (keep 7 days)
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
echo "Cleaned up backups older than 7 days."

# 3. TimescaleDB Chunk Statistics
echo "Checking chunk statistics..."
docker exec ivms_project-db-1 psql -U $DB_USER -d $DB_NAME -c "SELECT hypertable_name, chunk_name, range_start, range_end FROM timescaledb_information.chunks ORDER BY range_start DESC LIMIT 5;"

# 4. Refresh Continuous Aggregates
echo "Refreshing fleet daily aggregates..."
docker exec ivms_project-db-1 psql -U $DB_USER -d $DB_NAME -c "CALL refresh_continuous_aggregate('fleet_daily_summary', NULL, NULL);"

echo "--- Maintenance Completed Successfully ---"
