import os
import time
from dotenv import load_dotenv
from monitroing.kafka import start_consuming
from monitroing.k8s import watch_pod_logs, stop_all_threads
from monitroing.health import app, set_ready
import argparse
import uvicorn
import threading
from logger import logger


def start_health_server(port: int = 8000):
    """Start the health check server in a separate thread"""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()
    return thread

if __name__ == "__main__":
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Kubernetes Pod Log Monitor")
    
    parser.add_argument("-k", "--kafka", action="store_true", help="Use monitoring mode")
    parser.add_argument("--namespace", type=str, default=os.getenv("MONITORING_NAMESPACE"), help="Namespace to monitor")
    parser.add_argument("--selector", type=str, default=os.getenv("MONITORING_SELECTOR"), help="Label selector to filter pods")
    parser.add_argument("--topic", type=str, default=os.getenv("KAFKA_TOPIC"), help="Kafka topic to publish logs to")
    parser.add_argument("--health-port", type=int, default=8000, help="Port for health check server")
    
    args = parser.parse_args()
    
    # Start health check server
    health_thread = start_health_server(args.health_port)
    logger.info(f"Health check server started on port {args.health_port}")
    
    if args.kafka:
        logger.info(f"Starting Kafka consumer for topic: {args.topic}")
        start_consuming(args.topic)
    else:
        logger.info(f"Starting pod log monitoring in namespace: {args.namespace}")
        
        watch_pod_logs(
            namespace=args.namespace,
            label_selector=args.selector,
        )
        
        # Set ready status to true after initialization
        set_ready(True)
        
        try:
            # Keep main thread running
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            stop_all_threads()