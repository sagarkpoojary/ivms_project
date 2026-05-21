#!/bin/bash
# IVMS Enterprise Backup Script
# Goal: Daily dump of TimescaleDB with rotation

BACKUP_DIR="/root/ivms_project/backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_NAME="ivmsdb"
DB_USER="ivmsuser"

mkdir -p $BACKUP_DIR

echo "Starting backup of $DB_NAME..."

# Dump database
docker exec ivms-db pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/${DB_NAME}_backup_$TIMESTAMP.sql.gz

if [ $? -eq 0 ]; then
    echo "Backup successful: ${DB_NAME}_backup_$TIMESTAMP.sql.gz"
    # Rotate backups
    find $BACKUP_DIR -name "${DB_NAME}_backup_*.sql.gz" -mtime +$RETENTION_DAYS -exec rm {} \;
    echo "Old backups pruned."
else
    echo "BACKUP FAILED!"
    exit 1
fi
