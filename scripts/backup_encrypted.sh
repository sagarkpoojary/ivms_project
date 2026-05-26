#!/bin/bash
# ===========================================================================
# IVMS Enterprise Encrypted Database Backup Script (Oman/GCC Sovereignty Hardened)
# ===========================================================================
# Captures TimescaleDB daily snapshot, compresses, encrypts with PGP/GPG,
# and enforces a 7-day retention rotation policy.

BACKUP_DIR="/root/ivms_project/backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_NAME="ivmsdb"
DB_USER="ivmsuser"

# Configuration for symmetrical PGP encryption
# In a full production HSM deployment, retrieve this securely via KMS
PASSPHRASE_ENV_VAR=${IVMS_BACKUP_PASSPHRASE:-"OmanComplianceSecret2026"}

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting encrypted database snapshot of $DB_NAME..."

# Step 1: Dump database via Gzip
TEMP_DUMP="/tmp/${DB_NAME}_dump_${TIMESTAMP}.sql.gz"
docker exec ivms-db pg_dump -U $DB_USER $DB_NAME | gzip > "$TEMP_DUMP"

if [ ${PIPESTATUS[0]} -eq 0 ] && [ -f "$TEMP_DUMP" ]; then
    echo "[$(date)] Snapshot successfully compressed. Applying GPG encryption..."
    
    # Step 2: Encrypt compressed file using symmetrical PGP
    TARGET_ENCRYPTED_FILE="$BACKUP_DIR/${DB_NAME}_backup_${TIMESTAMP}.sql.gz.gpg"
    
    echo "$PASSPHRASE_ENV_VAR" | gpg --batch --yes --passphrase-fd 0 \
        --symmetric --cipher-algo AES256 \
        --output "$TARGET_ENCRYPTED_FILE" "$TEMP_DUMP"
        
    if [ $? -eq 0 ] && [ -f "$TARGET_ENCRYPTED_FILE" ]; then
        echo "[$(date)] Encrypted backup stored securely: $TARGET_ENCRYPTED_FILE"
        rm -f "$TEMP_DUMP" # clean temporary unencrypted snapshot
        
        # Step 3: Implement Rotation Policy
        find "$BACKUP_DIR" -name "${DB_NAME}_backup_*.sql.gz.gpg" -mtime +$RETENTION_DAYS -exec rm -f {} \;
        echo "[$(date)] Rotation complete. Backups older than $RETENTION_DAYS days pruned."
        exit 0
    else
        echo "[ERROR] PGP/GPG symmetric encryption failed!"
        rm -f "$TEMP_DUMP"
        exit 1
    fi
else
    echo "[ERROR] Database dump or Gzip compression failed!"
    exit 1
fi
