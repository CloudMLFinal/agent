import os

from kubernetes import client, config
import threading
import time
import argparse
import sys
import re
from datetime import datetime

#logger
import logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    ERROR = '\033[91m'
    ENDC = '\033[0m'


def watch_pod_logs(namespace, label_selector=None):
    """
    Kubernetes logging monitor
    参数:
        namespace (str): 命名空间名称
        label_selector (str, optional): Pod 标签选择器 (例如 "app=nginx")
        tail_lines (int, optional): 日志尾部行数
        follow (bool, optional): 是否持续跟踪日志
        since_seconds (int, optional): 获取过去多少秒的日志
    """
    if not namespace:
        print("❌ No namespace provided")
        raise ValueError("No namespace provided")

    # load kubeconfig config
    try:
        # try to load kubeconfig from local file
        config.load_kube_config()
        print("✅ Get kubeconfig Context")
    except Exception:
        try:
            config.load_incluster_config()
            print("✅ Get kubeconfig In Cluster")
        except Exception as e:
            print(f"❌ Failed to load Kubernetes config: {e}")
            sys.exit(1)

    # create Kubernetes API client
    v1 = client.CoreV1Api()
    # 获取要监听的 pod 列表
    pod_list = []

    # 使用标签选择器
    try:
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
        pod_list.extend(pods.items)
        if not pod_list:
            print(f"❌ 未找到匹配标签选择器 '{label_selector}' 的 Pod")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 无法获取 Pod 列表: {e}")
        sys.exit(1)


    def stream_logs(pod, container=None):
        pod_name = pod.metadata.name

        # 如果未指定容器，则使用第一个容器
        if not container and pod.spec.containers:
            container = pod.spec.containers[0].name

        print(f"{Colors.HEADER}开始监听 {namespace}/{pod_name}/{container} 的日志...{Colors.ENDC}")

        try:
            # 创建日志流
            logs_stream = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                follow=True,
                _preload_content=False
            )

            # 设置一个正则表达式来识别日志级别
            log_level_pattern = re.compile(r'\b(ERROR|WARN|INFO|DEBUG)\b', re.IGNORECASE)

            for line in logs_stream:
                if not line:
                    continue

                try:
                    log_line = line.decode('utf-8').rstrip()
                    # 添加时间戳
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    # 根据日志级别设置颜色
                    colored_line = log_line
                    match = log_level_pattern.search(log_line)
                    if match:
                        level = match.group(1).upper()
                        if level == 'ERROR':
                            colored_line = f"{Colors.ERROR}{log_line}{Colors.ENDC}"
                        elif level == 'WARN':
                            colored_line = f"{Colors.WARNING}{log_line}{Colors.ENDC}"
                        elif level == 'INFO':
                            colored_line = f"{Colors.GREEN}{log_line}{Colors.ENDC}"
                        elif level == 'DEBUG':
                            colored_line = f"{Colors.BLUE}{log_line}{Colors.ENDC}"

                    print(f"[{timestamp}] {namespace}/{pod_name}/{container}: {colored_line}")

                except UnicodeDecodeError:
                    # 处理二进制日志
                    print(f"[{timestamp}] {namespace}/{pod_name}/{container}: [二进制日志数据]")

            # 如果不是跟踪模式，日志读取结束后会退出流
            if not follow:
                print(f"{Colors.HEADER}已完成读取 {namespace}/{pod_name}/{container} 的日志{Colors.ENDC}")

        except client.rest.ApiException as e:
            print(f"❌ 读取日志时出错 ({namespace}/{pod_name}/{container}): {e}")
        except Exception as e:
            print(f"❌ 监听日志时发生未知错误: {e}")

    # 为每个 pod 创建一个线程来监听日志
    threads = []

    for pod in pod_list:
        for container in pod.spec.containers:
            thread = threading.Thread(target=stream_logs, args=(pod, container.name))
            threads.append(thread)

    # 启动所有线程
    for thread in threads:
        thread.start()

    try:
        # 等待所有线程完成
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n👋 监听已停止")
        sys.exit(0)


if __name__ == "__main__":
    watch_pod_logs(
        namespace=os.getenv("MONITORING_NAMESPACE"),
        label_selector=os.getenv("MONITORING_SELECTOR"),
    )