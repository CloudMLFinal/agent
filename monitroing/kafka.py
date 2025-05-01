from io import TextIOWrapper
from kafka import KafkaConsumer
import json
import logging
import os
import re
from datetime import datetime
from subprocess import Popen
from pathlib import Path
from tools.github import GithubRepoClient
import tempfile


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
                    current_dir = Path(__file__).parent.absolute()
                    agent_path = current_dir.parent / "agent.py"
                    
                    # Create a temporary file with the error buffer content
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
                        temp_file.write(error_buffer)
                        temp_file_path = Path(temp_file.name)
                    
                    # Analyze error and check for existing PR
                    file_path, feature_id, line_number = github_client.analyze_error(temp_file_path)
                    if file_path and not github_client.check_existing_pr(feature_id):
                        logger.info(f"Found new error in {file_path}:{line_number}, feature_id: {feature_id}")
                        Popen(["python", str(agent_path), str(temp_file_path), feature_id])
                    else:
                        logger.info(f"Skipping error as PR already exists or couldn't analyze error: {feature_id}")
                        
                    # Clean up the temporary file
                    os.unlink(temp_file_path)
                            
                    in_error_block = False
                    error_buffer = ""
                continue
            print(log_line.strip())
    except KeyboardInterrupt:
        logger.info("Stopping the consumer...")
    finally:
        consumer.close()
        logger.info("Consumer closed")