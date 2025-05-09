import re
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum

class LogLevel(Enum):
    NEED_ANALYSE = "NEED_ANALYSE"  # Default level, needs further analysis
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"
    CRITICAL = "CRITICAL"

class MessagePackage:
    def __init__(self, metadata: dict, message: str = "", level: LogLevel = LogLevel.NEED_ANALYSE):
        self.message = message
        self.metadata = metadata
        self.level = level
        self._created_at = datetime.now()
        
    def __str__(self):
        return f"MessagePackage(message={self.message}, metadata={self.metadata}, level={self.level.value})"
    
    @staticmethod
    def analyze_log_level(log_line: str) -> LogLevel:
        """
        Analyze the log level from a log line
        
        Args:
            log_line: The log line to analyze
            
        Returns:
            The detected log level
        """
        # Regular expressions for log level detection
        error_pattern = re.compile(r'\b(ERROR|Exception|Error|Failed|Failure)\b', re.IGNORECASE)
        warning_pattern = re.compile(r'\b(WARN|Warning)\b', re.IGNORECASE)
        info_pattern = re.compile(r'\b(INFO|Information)\b', re.IGNORECASE)
        debug_pattern = re.compile(r'\b(DEBUG|Debug)\b', re.IGNORECASE)
        critical_pattern = re.compile(r'\b(CRITICAL|Fatal|FATAL)\b', re.IGNORECASE)
        
        # Check for stack traces
        if re.match(r'Traceback \(most recent call last\):', log_line):
            return LogLevel.ERROR
            
        # Check for specific error patterns
        if critical_pattern.search(log_line):
            return LogLevel.CRITICAL
        elif error_pattern.search(log_line):
            return LogLevel.ERROR
        elif warning_pattern.search(log_line):
            return LogLevel.WARNING
        elif info_pattern.search(log_line):
            return LogLevel.INFO
        elif debug_pattern.search(log_line):
            return LogLevel.DEBUG
            
        return LogLevel.NEED_ANALYSE
    
    @staticmethod
    def package_log(log: str, metadata: Dict[str, Any]) -> 'MessagePackage':
        """
        Package a log message with metadata
        
        Args:
            log: The log message to package
            metadata: Metadata about the log source
            
        Returns:
            A MessagePackage object containing the log and metadata
        """
        level = MessagePackage.analyze_log_level(log)
        return MessagePackage(metadata=metadata, message=log, level=level)
    
    @staticmethod
    def package_multiline_log(log_lines: List[str], metadata: Dict[str, Any]) -> 'MessagePackage':
        """
        Package multiple log lines with metadata
        
        Args:
            log_lines: List of log lines to package
            metadata: Metadata about the log source
            
        Returns:
            A MessagePackage object containing the joined log lines and metadata
        """
        joined_lines = "\n".join(log_lines)
        # For multiline logs, analyze the first line for level
        level = MessagePackage.analyze_log_level(log_lines[0] if log_lines else "")
        return MessagePackage(metadata=metadata, message=joined_lines, level=level)
    
    @staticmethod
    def write_error_log(log_line: str, metadata: Dict[str, Any], 
                        in_error_block: bool, err_file: Optional[Any] = None) -> tuple[bool, Any]:
        """
        Write error logs to a separate file
        
        Args:
            log_line: The log line to process
            metadata: Metadata about the log source
            in_error_block: Whether we're currently in an error block
            err_file: The current error file handle (if any)
            
        Returns:
            Tuple of (in_error_block, err_file) updated state
        """
        # Regular expressions for log parsing
        
        TIMESTAMP_LINE_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}")
        DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
        
        # Error log directory
        ERROR_DIR = "errors"
        os.makedirs(ERROR_DIR, exist_ok=True)
        
        if not in_error_block and (" ERROR " in log_line or " CRITICAL " in log_line):
            # Start a new error block
            ts_match = DATETIME_RE.search(log_line)
            ts_str = (
                ts_match.group(0).replace("-", "").replace(":", "").replace(" ", "_")
                if ts_match
                else datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            )
            filename = os.path.join(ERROR_DIR, f"error_{metadata['pod_name']}_{metadata['container']}_{ts_str}.txt")
            err_file = open(filename, "w", encoding="utf-8")
            in_error_block = True
            err_file.write(log_line + "\n")
            err_file.flush()
        elif in_error_block:
            # Continue writing to error file
            if not TIMESTAMP_LINE_RE.match(log_line):
                if err_file:
                    err_file.write(log_line + "\n")
                    err_file.flush()
            elif TIMESTAMP_LINE_RE.match(log_line) and (
                " ERROR " not in log_line and " CRITICAL " not in log_line
            ):
                # End of error block
                if err_file:
                    err_file.close()
                    err_file = None
                in_error_block = False        
        return in_error_block, err_file

    @property
    def created_at(self):
        return self._created_at
