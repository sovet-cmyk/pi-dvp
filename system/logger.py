import logging
from logging.handlers import RotatingFileHandler
from app import config

logger = logging.getLogger("DVP")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s")
    handler = RotatingFileHandler(config.LOGS_DIR / "dvp.log", maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

