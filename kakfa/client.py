from kafka import KafkaConsumer
from kafka.errors import KafkaError, NoBrokersAvailable
import json
import logging
import socket
import time

# Force IPv4
socket.getaddrinfo('localhost', None, socket.AF_INET)

host = "127.0.0.1"  # Explicitly using IPv4 localhost
port = 37083

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,  # Changed to DEBUG level for more detailed logs
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

def create_kafka_consumer(topic_name, group_id=None):
    """
    Create a Kafka consumer instance
    :param topic_name: Name of the Kafka topic to consume from
    :param group_id: Consumer group ID (optional)
    :return: KafkaConsumer instance
    """
    try:
        consumer = KafkaConsumer(
            topic_name,
            bootstrap_servers=[f'{host}:{port}'],
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            value_deserializer=lambda x: json.loads(x.decode('utf-8')),
            security_protocol="PLAINTEXT",
            api_version_auto_timeout_ms=10000,
            request_timeout_ms=15000,  # Increased request timeout
            session_timeout_ms=10000,
            heartbeat_interval_ms=3000
        )

        logger.info(f"Successfully connected to Kafka broker at {host}:{port}")
        return consumer
    except Exception as e:
        logger.error(f"Failed to create Kafka consumer: {str(e)}")
        raise

def start_consuming(topic_name, group_id=None):
    """
    Start consuming messages from the specified Kafka topic
    :param topic_name: Name of the Kafka topic to consume from
    :param group_id: Consumer group ID (optional)
    """
    consumer = create_kafka_consumer(topic_name, group_id)
    logger.info(f"Started consuming messages from topic: {topic_name}")
    
    try:
        for message in consumer:
            try:
                logger.info(f"Received message: {message.value}")
                # Process your message here
                # You can add your custom processing logic
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                continue
    except KeyboardInterrupt:
        logger.info("Stopping the consumer...")
    finally:
        consumer.close()
        logger.info("Consumer closed")

if __name__ == "__main__":
    TOPIC_NAME = "cloudml-logs"
    logger.info(f"Starting consumer with topic: {TOPIC_NAME}")
    start_consuming(TOPIC_NAME)