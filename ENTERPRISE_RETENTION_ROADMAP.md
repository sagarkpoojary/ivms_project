# ENTERPRISE RETENTION ROADMAP & OMAN COMPLIANCE
**GCC Enterprise Readiness Assessment**
**Date:** May 31, 2026
**Status:** Completed (Audit & Planning Only)

---

## 1. Enterprise Plan Tiers

To onboard diverse fleet sizes, we propose four standard data retention plans. The capacity and infrastructure requirements are detailed below (assuming a standard fleet size of **500 vehicles**).

### 🥉 Bronze Plan (6-Month Retention)
* **Storage Requirement**: **~10.8 GB** (assuming optimized compression on telemetry and live updates).
* **Compression Requirements**:
  * Telemetry compressed after 7 days.
  * Live updates compressed after 7 days.
* **Backup Requirements**:
  * Encrypted daily backups, 30-day retention policy.
* **Infrastructure Impact**:
  * **Low**. Can easily run on the current single-instance VPS without upgrading disk space.

### 🥈 Silver Plan (1-Year Retention)
* **Storage Requirement**: **~21.6 GB** (optimized).
* **Compression Requirements**:
  * Telemetry compressed after 7 days.
  * Live updates compressed after 7 days.
* **Backup Requirements**:
  * Encrypted daily backups, 3-month retention policy.
* **Infrastructure Impact**:
  * **Low-Medium**. The current 76 GB free space is fully sufficient.

### 🥇 Gold Plan (3-Year Retention)
* **Storage Requirement**: **~64.8 GB** (optimized).
* **Compression Requirements**:
  * Telemetry compressed after 7 days.
  * Live updates compressed after 7 days.
* **Backup Requirements**:
  * Encrypted daily backups + weekly off-site archives. 1-year backup retention.
* **Infrastructure Impact**:
  * **Medium**. Requires upgrading the primary host disk to 150+ GB SSD to ensure adequate safety margin.

### 👑 Enterprise Plan (5+ Year Retention)
* **Storage Requirement**: **~108 GB** (optimized for 5 years) up to **3.8 TB** (if left unoptimized).
* **Compression Requirements**:
  * Strict TimescaleDB compression policies on all hypertables.
  * Automated migration of data older than 2 years to a cold, cheap S3 object storage tier.
* **Backup Requirements**:
  * Grandfather-Father-Son (GFS) rotation scheme. 5-year cold archiving in sovereign Oman glacier storage.
* **Infrastructure Impact**:
  * **High**. Requires clustered database deployment (TimescaleDB multi-node or read replicas) and S3-compatible cloud storage integrations.

---

## 2. Oman Enterprise Readiness & Compliance Audit

Evaluating IVMS readiness for highly regulated Middle Eastern markets:

```mermaid
radar
    title Oman Compliance Audit (Scores out of 5)
    "Data Residency (Sovereignty)" : 1
    "Backup Security" : 4
    "Disaster Recovery" : 2
    "System Hardening" : 3
    "Audit Trail Integrity" : 4
```

### 📋 Compliance Gap Analysis

1. **Oman Data Residency (Royal Decree 6/2022 - Personal Data Protection Law)**:
   * **Gap**: The current Docker Hub and PyPI dependencies are external. Local backups are stored on-host, but if replicated to standard AWS/GCP regions outside Oman, this violates local law.
   * **Remediation**: Establish local hosting with Oman-based cloud partners (Oman Data Park, Ooredoo, or Omantel). Ensure all S3 backup stores are physically inside Omani borders.
2. **Oil & Gas sector requirements (PDO - Petroleum Development Oman)**:
   * **Gap**: PDO requires rigorous real-time driver tracking, severe speed violation alerts, and robust RFID driver identification. Furthermore, continuous audit logs of driver attendance and vehicle maintenance must be retained for at least 5 years.
   * **Remediation**: The current 1-year telemetry retention must be upgraded to the **Enterprise Plan (5+ years)** with cold-storage tiering. Convert `driver_attendance` and `maintenance_history` tables to high-availability schemas with explicit daily off-site backups.
3. **Logistics & Enterprise Fleet Operators**:
   * **Gap**: Multi-tenancy isolation is critical. Currently, data isolation relies on basic application logic. If a shared-database failure occurs, the blast radius affects all customers.
   * **Remediation**: Migrate to an **isolated-schema or isolated-database-instance per tenant** hybrid architecture to ensure total customer data isolation.
