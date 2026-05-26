# IVMS Enterprise Operations Runbooks

This manual contains action guides for system administrators to address system limits, reboots, and SSL updates.

## Runbook 1: Production Reboot Sequence
Whenever the physical VPS host requires a scheduled reboot:
1. **Dampen Alerts**: Pause Alertmanager monitoring notifications.
2. **Graceful Drain**: Run `docker compose stop web api` to let Gunicorn clear requests.
3. **Shutdown db & ingestion**: Run `docker compose down`.
4. **Reboot VPS host**.
5. **Boot system**: Run `/root/ivms_project/install.sh` to trigger bootstrapping, volume allocation, containers boot, and readiness validations.

## Runbook 2: SSL/TLS Certificate Renewal
Self-signed certificates are valid for 365 days. To renew:
1. **Force delete current keys**:
   ```bash
   rm -f /root/ivms_project/nginx/ssl/server.*
   ```
2. **Trigger setup script**:
   ```bash
   ./setup_ssl.sh
   ```
3. **Reload Nginx reverse proxy**:
   ```bash
   docker exec ivms-nginx nginx -s reload
   ```
4. **Audit check**: Run `/root/ivms_project/verify-production.sh` to assert new certificate dates are detected.
