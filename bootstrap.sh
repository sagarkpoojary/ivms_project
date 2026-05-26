#!/bin/bash
# ===========================================================================
# IVMS Host Bootstrap Script
# ===========================================================================
# - Configures sysctl networking limits
# - Optimizes file descriptors
# - Verifies Docker & Compose package dependencies

echo "[BOOTSTRAP] Tuning OS sysctl parameter limits..."

# Increase file descriptor constraints
ulimit -n 65535
sysctl -w fs.file-max=2097152 >/dev/null 2>&1

# Optimize socket queues for Teltonika High-Throughput loads
sysctl -w net.core.somaxconn=1024 >/dev/null 2>&1
sysctl -w net.ipv4.tcp_max_syn_backlog=2048 >/dev/null 2>&1

# Verify Docker CE is available
if ! command -v docker &> /dev/null; then
    echo "[INFO] Installing Docker package dependency..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
else
    echo "[OK] Docker is installed: $(docker --version | awk '{print $3}')"
fi

# Verify Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "[ERROR] Docker Compose plugin is missing! Please install compose before running."
    exit 1
else
    echo "[OK] Docker Compose is ready."
fi

echo "[BOOTSTRAP] Host preparation successfully completed."
exit 0
