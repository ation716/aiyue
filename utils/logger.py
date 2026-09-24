"""Return a named logger without configuring global handlers."""
import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
