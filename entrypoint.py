import uvicorn
import os
from logging_config import setup_logging

# Setup logging before importing app
log_level = os.getenv("LOG_LEVEL", "DEBUG")
log_file = os.getenv("LOG_FILE", None)
setup_logging(log_level=log_level, log_file=log_file)

from app import app
from logging_config import get_logger

logger = get_logger(__name__)

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting EphemeralChat server on {host}:{port}")
    uvicorn.run("app:app", host=host, port=port, reload=True)
