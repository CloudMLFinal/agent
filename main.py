from kakfa.client import start_consuming
import logging
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    TOPIC_NAME = "cloudml-logs"
    start_consuming(TOPIC_NAME)