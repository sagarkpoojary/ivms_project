#!/bin/bash
# ===========================================================================
# IVMS Disaster Recovery Decryption & Restore Validation Script
# ===========================================================================
# Verifies database restore capability in a safe, isolated verify database.

if [ -z "$1" ]; then
    echo "Usage: $0 /path/to/backup.sql.gz.gpg"
    exit 1
fi

ENCRYPTED_FILE="$1"
PASSPHRASE_ENV_VAR=${IVMS_BACKUP_PASSPHRASE:-"OmanComplianceSecret2026"}
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TEMP_DECRYPTED="/tmp/ivmsdb_decrypted_${TIMESTAMP}.sql.gz"
VERIFY_DB="ivmsdb_verify"

if [ ! -f "$ENCRYPTED_FILE" ]; then
    echo "[ERROR] Encrypted backup file does not exist: $ENCRYPTED_FILE"
    exit 1
fi

echo "[$(date)] Starting secure restore validation on $ENCRYPTED_FILE..."

# Step 1: Decrypt PGP backup
echo "$PASSPHRASE_ENV_VAR" | gpg --batch --yes --passphrase-fd 0 \
    --decrypt --output "$TEMP_DECRYPTED" "$ENCRYPTED_FILE"

if [ $? -ne 0 ] || [ ! -f "$TEMP_DECRYPTED" ]; then
    echo "[ERROR] PGP/GPG decryption failed!"
    exit 1
fi
echo "[$(date)] Decryption successful. Recreating verification database '$VERIFY_DB'..."

# Step 2: Set up verify DB
docker exec ivms-db psql -U ivmsuser -d postgres -c "DROP DATABASE IF EXISTS $VERIFY_DB;"
docker exec ivms-db psql -U ivmsuser -d postgres -c "CREATE DATABASE $VERIFY_DB;"

# Step 3: Restore database
echo "[$(date)] Restoring snapshot into verification database..."
gunzip -c "$TEMP_DECRYPTED" | docker exec -i ivms-db psql -U ivmsuser -d "$VERIFY_DB" > /dev/null

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    echo "[$(date)] Restore completed. Running data integrity checks..."
    
    # Step 4: Run analytical check query (SLA baseline)
    ROW_COUNT=$(docker exec ivms-db psql -U ivmsuser -d "$VERIFY_DB" -t -A -c "SELECT COUNT(*) FROM vehicles;")
    
    if [ "$ROW_COUNT" -gt 0 ]; then
        echo "[SUCCESS] Restore validation PASSED. Total vehicles in backup: $ROW_COUNT."
        
        # Log audit trail event
        docker exec ivms-db psql -U ivmsuser -d postgres -c "
            INSERT INTO security_audit (event_type, details, severity) 
            VALUES ('DR_VALIDATION_PASSED', 'Successfully decrypted and restored database with $ROW_COUNT vehicles.', 'INFO') 
            ON CONFLICT DO NOTHING;" 2>/dev/null
            
        docker exec ivms-db psql -U ivmsuser -d postgres -c "DROP DATABASE IF EXISTS $VERIFY_DB;"
        rm -f "$TEMP_DECRYPTED"
        exit 0
    else
        echo "[ERROR] Integrity check failed: Restore yielded 0 vehicles."
        docker exec ivms-db psql -U ivmsuser -d postgres -c "DROP DATABASE IF EXISTS $VERIFY_DB;"
        rm -f "$TEMP_DECRYPTED"
        exit 1
    fi
else
    echo "[ERROR] Database restore failed!"
    docker exec ivms-db psql -U ivmsuser -d postgres -c "DROP DATABASE IF EXISTS $VERIFY_DB;"
    rm -f "$TEMP_DECRYPTED"
    exit 1
fi
