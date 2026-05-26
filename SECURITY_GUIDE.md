# IVMS Enterprise Security Hardening Manual

This document details the security posture, defensive configurations, and rate-limiting structures deployed to protect the IVMS platform.

## 1. Network Perimeter Shields

### SSL/TLS Hardening
Binds high-strength Elliptic Curve Diffie-Hellman (ECDSA `secp384r1`) certificates and enforces `TLS 1.2` and `TLS 1.3` protocols in Nginx to block legacy cipher threats.

### Security Headers
Every downstream Nginx response carries modern security headers:
- `X-Frame-Options: SAMEORIGIN` (prevents clickjacking)
- `X-Content-Type-Options: nosniff` (prevents mime-sniffing exploits)
- `Strict-Transport-Security` (enforces HSTS encryption boundaries)

## 2. Request Throttling & API Limits
Rate limits are enforced at two levels:
1. **Nginx Ingress**: Limits incoming traffic per IP to `100 requests/minute` with a burst buffer of `20` using `limit_req_zone`.
2. **Flask Application (`middleware/rate_limiter.py`)**: Implements sliding-window limit tracking via Redis pipelines. Fails open gracefully to preserve service if Redis is down.
