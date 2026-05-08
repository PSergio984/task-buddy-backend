from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import config

limiter = Limiter(key_func=get_remote_address, enabled=config.RATE_LIMIT_ENABLED)
