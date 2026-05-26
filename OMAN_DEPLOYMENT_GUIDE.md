# Oman & GCC Enterprise Compliance Guide

This guide details data residency, sovereignty, and regulatory audit compliance rules for deploying IVMS inside Oman and other GCC government datacenters.

## 1. Local Data Residency
Omani regulatory laws demand that all vehicle tracking telemetry, customer credentials, and database backups remain fully inside Omani borders:
- **No External CDN/DNS Routing**: Nginx serves all static assets directly. No Google Fonts, unapproved package CDNs, or foreign DNS resolvers are used.
- **Local Storage Enforcements**: Docker volumes and TimescaleDB data directories are physically mapped to local VPS storage nodes.

## 2. Secure Backups & Auditing
- **Backup Encryption**: Every daily backup is encrypted using symmetric `AES-256` keys to prevent data harvesting.
- **Traceability**: Administrative exports, login attempts, and ticket transitions are recorded in the `security_audit` TimescaleDB table. Logs are retained for a minimum compliance window of 5 years.
