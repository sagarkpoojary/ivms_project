import time
import logging
from flask import request, jsonify
import redis
from config import Config

logger = logging.getLogger("ivms.security")

class RedisRateLimiter:
    """
    Redis-Backed Sliding Window Rate Limiter.
    Limits clients to 100 requests per minute per IP.
    Fails open gracefully if Redis is fully down (reliability guarantee).
    """
    def __init__(self, app=None, limit=100, period=60):
        self.limit = limit
        self.period = period
        self.redis_client = None
        
        try:
            self.redis_client = redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                db=Config.REDIS_DB,
                socket_timeout=1.0  # short timeout to avoid blocking requests
            )
            # Ping once to check connection
            self.redis_client.ping()
            logger.info("Redis Rate Limiter initialized successfully.")
        except Exception as e:
            logger.warning(f"Redis Rate Limiter failed to connect: {e}. Running in FAIL-OPEN fallback mode.")
            self.redis_client = None
            
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        @app.before_request
        def check_rate_limit():
            # Bypass rate limit checks for local health probes
            if request.path in ('/health', '/ready', '/nginx-health', '/metrics'):
                return

            if not self.redis_client:
                # Fail-open if Redis is down
                return

            ip = request.headers.get('X-Real-IP') or request.remote_addr or 'unknown'
            key = f"rate_limit:{ip}"
            now = time.time()

            try:
                # Use Redis pipeline to run transaction-safe commands
                pipe = self.redis_client.pipeline()
                
                # Remove timestamps older than our rate-limit sliding window period
                pipe.zremrangebyscore(key, 0, now - self.period)
                # Count elements currently in our active sliding window bucket
                pipe.zcard(key)
                # Add current request timestamp
                pipe.zadd(key, {str(now): now})
                # Set TTL on key to auto-clean inactive buckets
                pipe.expire(key, self.period + 10)
                
                _, count, _, _ = pipe.execute()
                
                if count > self.limit:
                    logger.warning(f"Rate limit exceeded for IP {ip}: {count} requests inside window.")
                    return jsonify({
                        "status": "error",
                        "message": "Too many requests. Please slow down and try again.",
                        "limit": self.limit,
                        "window_seconds": self.period
                    }), 429
            except Exception as e:
                # Fail-open on Redis timeout or failure
                logger.error(f"Rate Limiter error during execution: {e}. Bypassing limit.")
                return
