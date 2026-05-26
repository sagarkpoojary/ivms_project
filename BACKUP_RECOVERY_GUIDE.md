# IVMS Encrypted Backups & Rotation Manual

This guide describes the automated database archiving system, file encryptions, and weekly rotation practices deployed inside the IVMS platform.

## 1. Automated Encryption Pipeline

The daily cron job executes `/root/ivms_project/scripts/backup_encrypted.sh` which:
1. Performs a compressed TimescaleDB dump.
2. Encrypts the snapshot using GPG with `AES-256` cipher algorithm.
3. Automatically deletes backups older than 7 days (`RETENTION_DAYS=7`).

```
                ┌──────────────────────────────────┐
                │     TimescaleDB Database Dump    │
                └────────────────┬─────────────────┘
                                 │
                                 ▼ (Gzip Compress)
                ┌──────────────────────────────────┐
                │       Compressed Snapshot        │
                └────────────────┬─────────────────┘
                                 │
                                 ▼ (PGP/GPG AES-256)
                ┌──────────────────────────────────┐
                │      Encrypted .gpg Backup       │
                └──────────────────────────────────┘
```

## 2. Decryption & Restore Command

To restore an encrypted `.gpg` backup into production:
```bash
./scripts/restore_encrypted.sh /root/ivms_project/backups/ivmsdb_backup_XXXXXXXX.sql.gz.gpg
```
This script will decrypt, verify integrity, restore schemas, and log audit confirmation.
