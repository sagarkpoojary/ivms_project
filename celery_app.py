import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "ivms_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.reports", "tasks.analytics", "tasks.cleanup"]
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Muscat',
    enable_utc=True,
    
    # Reliability & Scalability Hardening
    task_acks_late=True, # Ensure tasks are only acknowledged after completion
    worker_prefetch_multiplier=1, # One task per worker at a time for fair distribution
    task_reject_on_worker_lost=True,
    
    # Retry & DLQ Strategy
    task_publish_retry=True,
    task_publish_retry_policy={
        'max_retries': 3,
        'interval_start': 0,
        'interval_step': 0.2,
        'interval_max': 0.5,
    },
    
    # Metrics & Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True
)

@celery_app.task(bind=True, max_retries=5, default_retry_delay=30)
def debug_task(self):
    print(f'Request: {self.request!r}')

if __name__ == "__main__":
    celery_app.start()
