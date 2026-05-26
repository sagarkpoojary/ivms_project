# IVMS Single-Press Enterprise Deployment Guide

This guide details the steps to bootstrap and deploy the complete, microservices-orchestrated IVMS telematics stack on a fresh Ubuntu or AlmaLinux VPS.

## 1. Prerequisites
- **Operating System**: Ubuntu 22.04 LTS or AlmaLinux 9 (x86_64).
- **Minimum Specifications**: 4 vCPU, 8GB RAM, 80GB SSD.
- **Port Allocation**:
  - `80` (HTTP web proxy)
  - `443` (HTTPS web proxy)
  - `5027` (TCP Teltonika telematics listener)

## 2. One-Command Setup

Simply navigate to the workspace directory and execute the platform installer:
```bash
./install.sh
```

### What the installer executes:
1. **Bootstrap Host (`bootstrap.sh`)**: Enforces kernel-level `sysctl` socket limits and configures Docker CE.
2. **Hardens TLS Certificates (`setup_ssl.sh`)**: Sets up high-strength ECDSA `secp384r1` certs under `/nginx/ssl/`.
3. **Environment Setup**: Provisions secure, random secrets for Flask cookie sessions and API authorization.
4. **Initializes Database (`init_database.sh`)**: Registers TimescaleDB extensions, seeds core pricing structures, and applies database query index optimizations.
5. **Verifies Health**: Pings container `/ready` probes to guarantee zero-downtime startup readiness.
