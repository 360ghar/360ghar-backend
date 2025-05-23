"""
Celery configuration for ghar360 project.
"""

import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ghar360.settings')

app = Celery('ghar360')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery beat configuration for periodic tasks
app.conf.beat_schedule = {
    'check-saved-searches': {
        'task': 'search.tasks.check_saved_searches',
        'schedule': 300.0,  # Run every 5 minutes
    },
    'update-market-analytics': {
        'task': 'analytics.tasks.update_market_analytics',
        'schedule': 3600.0,  # Run every hour
    },
    'cleanup-expired-tokens': {
        'task': 'authentication.tasks.cleanup_expired_tokens',
        'schedule': 86400.0,  # Run daily
    },
    'generate-daily-reports': {
        'task': 'analytics.tasks.generate_daily_reports',
        'schedule': 86400.0,  # Run daily at midnight
    },
}

app.conf.timezone = 'Asia/Kolkata'

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}') 