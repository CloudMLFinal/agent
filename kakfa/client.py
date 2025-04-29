from kafka import KafkaConsumer
import json
import logging
import os
import re
from datetime import datetime
from subprocess import Popen
from pathlib import Path

HOST = "localhost"
PORT = 30902

ERROR_DIR = "errors"        
os.makedirs(ERROR_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
)
logger = logging.getLogger(__name__)

TIMESTAMP_LINE_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}")     
DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")  


def create_kafka_consumer(topic_name: str, group_id: str | None = None) -> KafkaConsumer:
    """Create a Kafka consumer instance"""
    consumer = KafkaConsumer(
        topic_name,
        group_id=group_id,
        bootstrap_servers=[f"{HOST}:{PORT}"],
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    logger.info(f"Successfully connected to Kafka broker at {HOST}:{PORT}")
    return consumer


def start_consuming(topic_name: str, group_id: str | None = None) -> None:
    """Consume messages; for each ERROR/CRITICAL block write a separate txt"""
    consumer = create_kafka_consumer(topic_name, group_id)
    logger.info(f"Started consuming messages from topic: {topic_name}")

    in_error_block = False
    err_file = None                      

    try:
        for msg in consumer:
            try:
                data = json.loads(msg.value.decode("utf-8"))
                log_line = data.get("log", "")
            except Exception as exc:   
                logger.error(f"Bad message, skip: {exc}")
                continue

      
            if not in_error_block and (" ERROR " in log_line or " CRITICAL " in log_line):
                ts_match = DATETIME_RE.search(log_line)
                ts_str = (
                    ts_match.group(0).replace("-", "").replace(":", "").replace(" ", "_")
                    if ts_match
                    else datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                )
                filename = os.path.join(ERROR_DIR, f"error_{ts_str}.txt")   # ← 路径拼接
                err_file = open(filename, "w", encoding="utf-8")
                in_error_block = True
                continue

       
            if in_error_block:
                if not TIMESTAMP_LINE_RE.match(log_line):
                    err_file.write(log_line)
                    err_file.flush()

            
                if TIMESTAMP_LINE_RE.match(log_line) and (
                    " ERROR " not in log_line and " CRITICAL " not in log_line
                ):
                    err_file.close()
                    current_dir = Path(__file__).parent.absolute()
                    agent_path = current_dir.parent / "agent.py"
                    error_path = Path(err_file.name).absolute()
                    
                 
                    Popen([
                        "python", 
                        str(agent_path), 
                        str(error_path)
                    ])
                    logger.info(f"Triggered fix agent for : {error_path.name}")
                    in_error_block = False
                    err_file = None
                continue

            print(log_line.strip())

    except KeyboardInterrupt:
        logger.info("Stopping the consumer...")
    finally:
        consumer.close()
        if err_file and not err_file.closed:
            err_file.close()
        logger.info("Consumer closed")


if __name__ == "__main__":
    TOPIC_NAME = "cloudml-logs"
    logger.info(f"Starting consumer with topic: {TOPIC_NAME}")
    start_consuming(TOPIC_NAME)
