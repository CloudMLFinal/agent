import json

from kafka import KafkaConsumer
import logging

host = "localhost"
port = 30902

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
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
            group_id=group_id,
            bootstrap_servers=[f'{host}:{port}'],
            auto_offset_reset='earliest',
            enable_auto_commit=True
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
                parsed_message = json.loads(message.value.decode('utf-8'))
                print('---')
                print(parsed_message)
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
