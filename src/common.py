import os
import time
import base64
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta


def setup_logger(name: str = "lorawan-multicast-configurator", log_dir: str = "logs", level=logging.INFO) -> logging.Logger:
    """Setup a logger with console and rotating file handlers."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Avoid adding handlers multiple times

    logger.setLevel(level)
    logger.propagate = False

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, f"{name}.log")

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating File Handler, rotate at 5MB, keep 10 backups
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=10)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

def set_logger_level(level: str) -> None:
    """Update the logging level of the global logger."""
    level = level.upper()
    if level == 'DEBUG':
        logger.setLevel(logging.DEBUG)
    elif level == 'INFO':
        logger.setLevel(logging.INFO)
    elif level == 'WARNING':
        logger.setLevel(logging.WARNING)
    elif level == 'ERROR':
        logger.setLevel(logging.ERROR)
    elif level == 'CRITICAL':
        logger.setLevel(logging.CRITICAL)
    else:
        logger.setLevel(logging.INFO)  # Default to INFO if invalid level

# Create a global logger instance
logger = setup_logger()

class TerminateProcessException(Exception):
    """Custom exception to terminate current execution"""
    def __init__(self, msg: str, err: Exception | None = None) -> None:
        self.msg = msg
        self.err = err
        super().__init__(self.msg)
    def __str__(self) -> str:
        return f"Error! {self.msg} {self.err if self.err is not None else ''}"

class ConfigReaderException(Exception):
    def __init__(self, msg: str, err: Exception | None = None) -> None:
        self.msg = msg
        self.err = err
        super().__init__(self.msg)
    def __str__(self) -> str:
        return f"{self.msg} {self.err if self.err is not None else ''}"

def current_utc_time() -> datetime:
    """Returns current UTC time"""
    return datetime.now(timezone.utc)

def current_local_time() -> datetime:
    """Returns current time in local timezone"""
    return datetime.now()

def utc_to_local_time(utc_time: datetime):
    """Returns time in local timezone"""
    return utc_time.astimezone()

def get_gps_epoch_seconds() -> int:
    """
    Returns the current time in seconds since the GPS epoch (00:00:00 UTC, January 6, 1980).
    As of 2026, there are 18 leap seconds to account for.
    """
    gps_epoch = datetime(1980, 1, 6, tzinfo=timezone.utc)
    seconds_elapsed = (current_utc_time() - gps_epoch).total_seconds()
    leap_seconds = 18  # GPS is 18 seconds ahead of UTC as of Jan 2026
    return int(seconds_elapsed + leap_seconds)

def gps_seconds_to_datetime(gps_seconds) -> datetime:
    """
    Converts seconds since GPS Epoch (Jan 6, 1980) to a UTC datetime object.
    As of 2026, there are 18 leap seconds to account for.
    """
    gps_epoch = datetime(1980, 1, 6, tzinfo=timezone.utc)
    leap_seconds = 18  # GPS is 18 seconds ahead of UTC as of Jan 2026
    utc_datetime = gps_epoch + timedelta(seconds=(gps_seconds - leap_seconds))
    return utc_datetime

def time_remaining_till_target_time(target_time: datetime) -> timedelta:
    return target_time.replace(microsecond=0) - current_utc_time().replace(microsecond=0)

def time_elapsed_since(start_time: datetime) -> timedelta:
    return current_utc_time().replace(microsecond=0) - start_time.replace(microsecond=0)

def sleep(seconds: float=0, minutes: float=0) -> None:
    """Sleep for the specified number of seconds, handling interruptions."""
    try:
        time.sleep(seconds + minutes*60)
    except InterruptedError:
        logger.warning("Sleep interrupted.")

compare_dictionaries_by_keys = lambda dict1, dict2: all(dict1.get(k) == dict2.get(k) for k in dict1.keys() & dict2.keys())

def base64_to_hex(base64_string):
    """
    Decodes a Base64 string to bytes, then converts the bytes to a hex string.
    """
    decoded_bytes = base64.b64decode(base64_string)
    hex_string = decoded_bytes.hex()
    return hex_string
