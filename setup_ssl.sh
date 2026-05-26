#!/bin/bash
# ===========================================================================
# IVMS TLS / SSL Security Certificate Automator
# ===========================================================================
# Generates a modern secure self-signed SSL/TLS keypair (ECDSA Secp384r1)
# if no external Let's Encrypt certificates are mounted in production.

SSL_DIR="/root/ivms_project/nginx/ssl"
mkdir -p "$SSL_DIR"

if [ -f "$SSL_DIR/server.crt" ] && [ -f "$SSL_DIR/server.key" ]; then
    echo "[SSL] SSL keypair already exists. Skipping certificate generation."
    exit 0
fi

echo "[SSL] SSL certificate keypair missing. Generating high-strength ECDSA certificate..."

# Generate elliptic curve secp384r1 private key
openssl ecparam -name secp384r1 -genkey -noout -out "$SSL_DIR/server.key"

# Create a self-signed certificate valid for 365 days
openssl req -new -x509 -key "$SSL_DIR/server.key" -out "$SSL_DIR/server.crt" -days 365 \
    -subj "/C=OM/L=Muscat/O=IVMS Enterprise/OU=Fleet Infrastructure/CN=72.61.254.210" \
    -sha384

if [ $? -eq 0 ]; then
    echo "[SSL] SSL/TLS ECDSA certificates generated successfully."
    chmod 600 "$SSL_DIR/server.key"
    chmod 644 "$SSL_DIR/server.crt"
    exit 0
else
    echo "[ERROR] OpenSSL certificate generation failed!"
    exit 1
fi
