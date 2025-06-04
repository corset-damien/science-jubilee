import logging
import os

class AlignedNameFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, maxlen=18):
        super().__init__(fmt, datefmt)
        self.maxlen = maxlen

    def format(self, record):
        name = record.name
        spaces = ' ' * (self.maxlen - len(name))
        record.spaces = spaces
        return super().format(record)

def setup_logging(
    log_dir="logs",
    log_file="jubilee.log",
    level=logging.INFO,
    logger_name=None,
) -> logging.Logger:
    """
    Configure and return a named logger.

    :param log_dir: Directory (relative to the science_jubilee package) where logs will be saved.
    :param log_file: Name of the log file.
    :param level: Logging level (e.g., logging.INFO).
    :param logger_name: Optional name for the logger.
    :return: Configured logger instance.
    """
    # Always place the logs directory inside the science_jubilee package root
    package_root = os.path.dirname(os.path.abspath(__file__))
    log_dir_abs = os.path.join(package_root, log_dir)
    os.makedirs(log_dir_abs, exist_ok=True)
    full_path = os.path.join(log_dir_abs, log_file)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # Clean up existing handlers to avoid duplicates or blocking
    if logger.hasHandlers():
        logger.handlers.clear()

    file_handler = logging.FileHandler(full_path, mode='a', encoding='utf-8')
    console_handler = logging.StreamHandler()

    formatter = AlignedNameFormatter(
        "%(asctime)s - [%(name)s]%(spaces)s - %(levelname)s - %(message)s",
        datefmt='%Y-%m-%d %H:%M:%S',
        maxlen=18 # Adjust this value to change the alignment width
    )

    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False

    return logger