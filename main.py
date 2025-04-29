from kakfa.client import start_consuming
import logging
import os
from dotenv import load_dotenv
from monitroing.logging import watch_pod_logs

if __name__ == "__main__":
    load_dotenv()
    TOPIC_NAME = "cloudml-logs"
    start_consuming(TOPIC_NAME)

    watch_pod_logs(
        namespace=os.getenv("MONITORING_NAMESPACE"),
        label_selector=os.getenv("MONITORING_SELECTOR"),
    )