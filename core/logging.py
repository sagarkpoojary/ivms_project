import logging
import json
import time
import uuid
from threading import local

_context = local()

class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(_context, "correlation_id", "system")
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)

def setup_logging(level=logging.INFO):
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(level)

def set_correlation_id(cid=None):
    _context.correlation_id = cid or str(uuid.uuid4())

def get_correlation_id():
    return getattr(_context, "correlation_id", None)
