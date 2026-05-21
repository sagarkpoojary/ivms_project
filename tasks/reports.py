from celery_app import celery_app
import logging

logger = logging.getLogger(__name__)

@celery_app.task
def generate_fleet_report(tenant_id, period):
    logger.info(f"Generating fleet report for {tenant_id} | Period: {period}")
    return {"status": "completed", "url": "/reports/dummy.pdf"}
