from kafka import KafkaConsumer
import json
import os
import re
from datetime import datetime
from agent.queue import CodeFixerQueue
from monitroing.package import LogLevel, MessagePackage
from tools.github import GithubRepoClient
from logger import logger


ERROR_DIR = "errors"  
os.makedirs(ERROR_DIR, exist_ok=True)
queue = CodeFixerQueue()

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
    consumer = create_kafka_consumer(topic_name, group_id)
    logger.info(f"Started consuming messages from topic: {topic_name}")

    in_error_block = False
    error_buffer = ""
    last_error_time = None
    MAX_LINES = 100 
    error_line_count = 0

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

            if not in_error_block and ("ERROR" in log_line or "CRITICAL" in log_line):
                in_error_block = True
                error_buffer = log_line + "\n"
                error_line_count = 1
                continue

     
            if in_error_block:
              
                if TIMESTAMP_LINE_RE.match(log_line) and not ("ERROR" in log_line or "CRITICAL" in log_line):
                    logger.info(f"Analyzing error:\n{error_buffer}")
                    queue.submit_job(MessagePackage({}, error_buffer, LogLevel.ERROR))
                    in_error_block = False
                    error_buffer = ""
                    error_line_count = 0
                else:
                    error_buffer += log_line + "\n"
                    error_line_count += 1
            
                    if error_line_count > MAX_LINES:
                        logger.warning(f"Max line reached for error block. Auto-submitting:\n{error_buffer}")
                        queue.submit_job(MessagePackage({}, error_buffer, LogLevel.ERROR))
                        in_error_block = False
                        error_buffer = ""
                        error_line_count = 0
                continue

       
            print(log_line.strip())

    except KeyboardInterrupt:
        logger.info("Stopping the consumer...")
    finally:
        consumer.close()
        logger.info("Consumer closed")