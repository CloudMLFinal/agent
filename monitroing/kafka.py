from io import TextIOWrapper
from kafka import KafkaConsumer
import json
import logging
import os
import re
from datetime import datetime
from subprocess import Popen
from pathlib import Path
from agent.queue import CodeFixerQueue
from monitroing.package import LogLevel, MessagePackage
from tools.github import GithubRepoClient
import tempfile


ERROR_DIR = "errors"  
os.makedirs(ERROR_DIR, exist_ok=True)

queue = CodeFixerQueue()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
)

logger = logging.getLogger(__name__)

TIMESTAMP_LINE_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}")     
DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")  

def create_kafka_consumer(topic_name: str, group_id: str | None = None) -> KafkaConsumer:
    if os.getenv("KAFKA_HOST"):
        HOST = os.getenv("KAFKA_HOST")
    if os.getenv("KAFKA_PORT"):
        PORT = os.getenv("KAFKA_PORT")
        
    assert HOST and PORT, "KAFKA_HOST and KAFKA_PORT must be set"
    
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
    error_buffer: str = ""
    
    # Initialize GitHub client
    repo_url = os.getenv("SOURCE_REPO")
    assert repo_url, "SOURCE_REPO must be set"
    github_client = GithubRepoClient(repo_url)

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
                error_buffer = log_line + "\n"
                in_error_block = True
                continue

            if in_error_block:
                if not TIMESTAMP_LINE_RE.match(log_line):
                    error_buffer += log_line + "\n"

                if TIMESTAMP_LINE_RE.match(log_line) and (
                    " ERROR " not in log_line and " CRITICAL " not in log_line
                ):
                    logger.info(f"Analyzing error: {error_buffer}")
                    queue.submit_job(MessagePackage({}, error_buffer, LogLevel.ERROR))
                    in_error_block = False
                    error_buffer = ""
                continue
            print(log_line.strip())
    except KeyboardInterrupt:
        logger.info("Stopping the consumer...")
    finally:
        consumer.close()
        logger.info("Consumer closed")