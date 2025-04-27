from kakfa.client import start_consuming

import logging
import os

logger = logging.getLogger()

if __name__ == "__main__":
    TOPIC_NAME = "cloudml-logs"
    start_consuming(TOPIC_NAME)