import os

from kubernetes import client, config
import threading
import time
import sys
import re
from datetime import datetime
from typing import Optional, Any, Dict, List, Union, cast
import select
import json
from .pos import PosPointer
from .package import MessagePackage
from agent.queue import CodeFixerQueue
from logger import logger


#deinf pod type
Pod = client.V1Pod
threads = []
v1 = None  # Will be initialized in watch_pod_logs

# Color codes for terminal output
class Colors:
    GRAY = '\033[90m'
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    ERROR = '\033[91m'
    ENDC = '\033[0m'
    RED = '\033[91m'

# Error log directory
ERROR_DIR = "errors"
os.makedirs(ERROR_DIR, exist_ok=True)

queue = CodeFixerQueue()

# Regular expressions for log parsing
TIMESTAMP_LINE_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}")
DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

def get_worker_status():
    # Status of the threads
    status = {
        "total_threads": len(threads),
        "running_threads": sum(1 for thread in threads if thread.is_alive()),
    }
    return status

def watch_pod_logs(namespace, label_selector=None):
    global v1
    """
    Kubernetes logging monitor
    Parameters:
        namespace (str): Namespace name
        label_selector (str, optional): Pod label selector (e.g. "app=nginx")
        tail_lines (int, optional): Number of lines to tail from the logs
        follow (bool, optional): Whether to continuously follow the logs
        since_seconds (int, optional): Get logs from the past X seconds
    """
    if not namespace:
        logger.error("❌ No namespace provided")
        raise ValueError("No namespace provided")

    # load kubeconfig config
    try:
        # try to load kubeconfig from local file
        config.load_kube_config()
        logger.info("✅ Get kubeconfig Context")
    except Exception:
        try:
            config.load_incluster_config()
            logger.info("✅ Get kubeconfig In Cluster")
        except Exception as e:
            logger.error(f"❌ Failed to load Kubernetes config: {e}")
            sys.exit(1)

    # create Kubernetes API client
    v1 = client.CoreV1Api()
    # Get the list of pods to monitor
    pod_list = []

    # Use label selector
    try:
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        pod_list.extend(pods.items)
        if not pod_list:
            logger.warn(f"❌ No pods found matching label selector '{label_selector}'")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unable to get pod list: {e}")
        sys.exit(1)

    class LogWorker(threading.Thread):
        def __init__(self, pod: Any, container: str, api_client: client.CoreV1Api):
            super().__init__()
            self.pos_pointer = PosPointer(f"{namespace}-{pod.metadata.name}-{container}")
            self.pod = pod
            self.container = container
            self._stop_event = threading.Event()
            self.daemon = True  # Make thread daemon so it exits when main thread exits
            self.api_client = api_client
            self.logs_stream = None
            self.pod_metadata = self._get_pod_metadata()
            self.name = f"LogWorker-{pod.metadata.name}-{container}"  # Give thread a meaningful name
            self.in_error_block = False
            self.err_file = None

        def _get_pod_metadata(self) -> Dict[str, Any]:
            """Get Pod metadata information"""
            
            # Get pod name and namespace
            pod_name = getattr(self.pod.metadata, 'name', 'unknown')
            namespace = getattr(self.pod.metadata, 'namespace', 'unknown')
            
            try:
                # Get detailed Pod information
                pod_details = self.api_client.read_namespaced_pod(name=pod_name, namespace=namespace)
                
                # Extract container information
                container_info = {}
                if hasattr(pod_details, 'spec') and hasattr(pod_details.spec, 'containers'):  # type: ignore
                    for container in pod_details.spec.containers:  # type: ignore
                        if container.name == self.container:
                            container_info = {
                                "image": getattr(container, 'image', 'N/A'),
                                "imagePullPolicy": getattr(container, 'image_pull_policy', 'N/A'),
                                "ports": [{"containerPort": getattr(port, 'container_port', 0), 
                                          "protocol": getattr(port, 'protocol', 'TCP')} 
                                         for port in getattr(container, 'ports', [])]
                            }
                            break
                
                # Build metadata dictionary
                metadata = {
                    "pod_name": pod_name,
                    "namespace": namespace,
                    "labels": getattr(self.pod.metadata, 'labels', {}),
                    "annotations": getattr(self.pod.metadata, 'annotations', {}),
                    "container": self.container,
                    "container_info": container_info,
                    "node_name": getattr(pod_details.spec, 'node_name', 'N/A'),  # type: ignore
                    "phase": getattr(pod_details.status, 'phase', 'N/A'),  # type: ignore
                    "start_time": getattr(pod_details.status, 'start_time', None)  # type: ignore
                }
                
                # Process start time
                if metadata["start_time"]:
                    metadata["start_time"] = metadata["start_time"].isoformat()
                
                # Print metadata information
                logger.debug(f"{Colors.HEADER}Pod Metadata: {pod_name}/{self.container}{Colors.ENDC}")
                logger.debug(f"{Colors.BLUE}Namespace: {metadata['namespace']}{Colors.ENDC}")
                logger.debug(f"{Colors.BLUE}Node: {metadata['node_name']}{Colors.ENDC}")
                logger.debug(f"{Colors.BLUE}Status: {metadata['phase']}{Colors.ENDC}")
                logger.debug(f"{Colors.BLUE}Start Time: {metadata['start_time']}{Colors.ENDC}")
                logger.debug(f"{Colors.BLUE}Image: {metadata['container_info'].get('image', 'N/A')}{Colors.ENDC}")

                if metadata['labels']:
                    logger.debug(f"{Colors.BLUE}Labels: {json.dumps(metadata['labels'], ensure_ascii=False)}{Colors.ENDC}")
                
                return metadata
            except Exception as e:
                logger.error(f"❌ Failed to get Pod metadata: {e}")
                return {
                    "pod_name": pod_name,
                    "namespace": namespace,
                    "container": self.container
                }

        def run(self) -> None:
            try:
                self.stream_logs()
            except Exception as e:
                logger.error(f"❌ Thread {self.name} encountered an error: {e}")
                # Don't re-raise the exception to keep the thread alive

        def stop(self) -> None:
            """Stop the thread gracefully"""
            self._stop_event.set()
            # Close the logs stream if it exists
            if self.logs_stream:
                try:
                    self.logs_stream.close()
                except:
                    pass
            # Close error file if open
            if self.err_file and not self.err_file.closed:
                self.err_file.close()

        def stream_logs(self) -> None:
            pod_name = getattr(self.pod.metadata, 'name', 'unknown')
            namespace = getattr(self.pod.metadata, 'namespace', 'unknown')
            if not self.container and hasattr(self.pod, 'spec') and hasattr(self.pod.spec, 'containers'):
                logger.error(f'No container specified')
                return

            logger.info(f"{Colors.HEADER}Starting to monitor logs for {namespace}/{pod_name}/{self.container}...{Colors.ENDC}")
            
            # multiline patterns
            log_prefix_pattern = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} -')
            error_start_pattern = re.compile(r'Traceback \(most recent call last\):')
            error_end_pattern = re.compile(r'^\w+Error: .*')
            
            # log line buffer
            log_line_buffer: List[str] = []
            in_error_stack = False
            
            retry_count = 0
            
            def flush_log_line_buffer():
                if log_line_buffer:
                    queue.submit_job(MessagePackage.package_multiline_log(log_line_buffer, self.pod_metadata))
                    log_line_buffer.clear()
            
            # Main monitoring loop
            while not self._stop_event.is_set():
                try:
                    # Create log stream
                    self.logs_stream = self.api_client.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        container=self.container,
                        follow=True,
                        since_seconds=None if self.pos_pointer.pos == 0 else int(datetime.now().timestamp() - self.pos_pointer.pos),
                        _preload_content=False
                    )
                    
                    logger.info(f"{Colors.GREEN}Successfully connected to log stream for {namespace}/{pod_name}/{self.container}{Colors.ENDC}")

                    # Read log stream in non-blocking mode
                    while not self._stop_event.is_set():
                        # Check if there is data to read, timeout 1 second
                        if select.select([self.logs_stream], [], [], 1)[0]:
                            retry_count = 0
                            # update pos pointer
                            self.pos_pointer.set(int(datetime.now().timestamp())).save_cache()
                            try:
                                # read the log line
                                line = self.logs_stream.readline()
                                
                                # if no new logs, continue the loop
                                if not line:
                                    # If no new logs, continue the loop
                                    flush_log_line_buffer()
                                    continue
                                
                                log_line: str = line.decode('utf-8').rstrip()
                                    
                                # Handle error logs using MessagePackage
                                self.in_error_block, self.err_file = MessagePackage.write_error_log(
                                    log_line, 
                                    self.pod_metadata, 
                                    self.in_error_block, 
                                    self.err_file
                                )
                                # Handle multiline logs
                                if error_start_pattern.match(log_line):
                                    # Start of error stack trace
                                    in_error_stack = True
                                    log_line_buffer.append(log_line)
                                elif in_error_stack:
                                    # Inside error stack trace
                                    log_line_buffer.append(log_line)
                                    if error_end_pattern.match(log_line):
                                        # End of error stack trace
                                        in_error_stack = False
                                        flush_log_line_buffer()
                                elif log_prefix_pattern.match(log_line):
                                    # Regular log line with timestamp
                                    flush_log_line_buffer()
                                    log_line_buffer.append(log_line)
                                else:
                                    # Continuation of previous log line
                                    log_line_buffer.append(log_line)
                            except Exception as e:
                                # Handle read exceptions
                                if not self._stop_event.is_set():
                                    # Only print error if not triggered by stop event
                                    logger.error(f"❌ Error reading log stream: {e}")
                                    # Short sleep to avoid excessive CPU usage
                                    time.sleep(0.5)
                        else:
                            # Timeout, continue loop
                            flush_log_line_buffer()
                            continue         
                except client.ApiException as e:
                    if not self._stop_event.is_set():
                        logger.error(f"❌ API Error when monitoring log ({namespace}/{pod_name}/{self.container}): {e}")
                        # Wait before retrying
                        time.sleep(5)
                        retry_count += 1
                        if retry_count > 3:
                            logger.error(f"🔌 Failed to monitor log for {namespace}/{pod_name}/{self.container} after 3 retries, terminate the worker")
                            break
                except Exception as e:
                    if not self._stop_event.is_set():
                        logger.error(f"❌ Unknown Error: {e}")
                        # Wait before retrying
                        time.sleep(5)
                finally:
                    # Ensure log stream is closed
                    if self.logs_stream:
                        try:
                            self.logs_stream.close()
                        except:
                            pass
                        
                    # Ensure error file is closed
                    if self.err_file and not self.err_file.closed:
                        self.err_file.close()
                    logger.warn(f"{Colors.RED}Log stream for {namespace}/{pod_name}/{self.container} closed{Colors.ENDC}")

    # Create a thread for each pod to monitor logs
    for pod in pod_list:
        for container in pod.spec.containers:
            thread = LogWorker(pod, container.name, v1)
            threads.append(thread)

    [thread.start() for thread in threads]
    
    logger.info(f"✅ {Colors.GREEN} {len(threads)} log monitoring threads have been started{Colors.ENDC}")

def stop_all_threads():
    """
    Stop all threads
    """
    logger.info("Stopping all log monitoring threads...")
    for thread in threads:
        if thread.is_alive():
            thread.stop()
    
    # Wait for threads to end
    for index in range(len(threads)):
        if threads[index].is_alive():
            threads[index].join(timeout=2)
            if threads[index].is_alive():
                logger.error(f"❌ Thread {threads[index].name} is still running, attempting to force terminate...")
                threads[index].terminate()
    
    threads.clear()
    
    logger.info("✅ All log monitoring threads have been stopped")
                