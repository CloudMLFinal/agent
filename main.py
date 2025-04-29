from kakfa.client import start_consuming
import logging
import os
from dotenv import load_dotenv
from monitroing.logging import watch_pod_logs, stop_all_threads
import argparse

logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Kubernetes Pod Log Monitor")
    parser.add_argument("-k", "--kafka", action="store_true", help="Use monitoring mode")
    parser.add_argument("--namespace", type=str, default=os.getenv("MONITORING_NAMESPACE"), help="Namespace to monitor")
    parser.add_argument("--selector", type=str, default=os.getenv("MONITORING_SELECTOR"), help="Label selector to filter pods")
    parser.add_argument("--topic", type=str, default=os.getenv("TOPIC_NAME"), help="Kafka topic to publish logs to")
    
    args = parser.parse_args()
    
    if args.kafka:
        logger.info(f"Starting Kafka consumer for topic: {args.topic}")
        start_consuming(args.topic)
    else:
        logger.info(f"Starting pod log monitoring in namespace: {args.namespace}")
        
        watch_pod_logs(
            namespace=args.namespace,
            label_selector=args.selector,
        )
        
        input("Press Enter to stop all threads")
        logger.info("Stopping all threads")
        stop_all_threads()