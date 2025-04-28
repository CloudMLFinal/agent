from kakfa.client import start_consuming

import logging
import os

logger = logging.getLogger()

if __name__ == "__main__":
    TOPIC = "cloudml-logs"
    logger.info(f"Starting consumer with topic: {TOPIC}")
    start_consuming(TOPIC)