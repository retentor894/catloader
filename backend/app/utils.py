"""
Utility functions for metrics collection, logging, and backoff calculation.

This module provides:
- Metrics: Thread-safe metrics collector for observability
- sanitize_for_log: Sanitize user data for safe logging
- calculate_backoff_delay: Exponential backoff calculation
- RETRYABLE_EXCEPTIONS: Tuple of exceptions that indicate transient errors

Note: The application does NOT use endpoint-level retry logic because yt-dlp
has internal retries (retries=3 in COMMON_OPTS). The backoff utilities are
kept for potential future use and as general-purpose utilities.
"""

import logging
import threading
from typing import Type, Tuple

from .config import RETRY_BASE_DELAY, RETRY_MAX_DELAY, METRICS_ENABLED
from .exceptions import TransientError

logger = logging.getLogger(__name__)

# =============================================================================
# Metrics Collection
# =============================================================================

class Metrics:
    """Thread-safe metrics collector for observability."""

    def __init__(self):
        self._lock = threading.Lock()
        self._timeout_count = 0
        self._retry_count = 0
        self._success_count = 0
        self._error_count = 0

    def record_timeout(self, endpoint: str, elapsed: float):
        """Record a timeout event."""
        with self._lock:
            self._timeout_count += 1
            count = self._timeout_count
        if METRICS_ENABLED:
            logger.info(
                f"METRIC timeout endpoint={endpoint} elapsed={elapsed:.2f}s "
                f"total_timeouts={count}"
            )

    def record_retry(self, operation: str, attempt: int, delay: float, error: str):
        """Record a retry attempt."""
        with self._lock:
            self._retry_count += 1
            count = self._retry_count
        if METRICS_ENABLED:
            logger.info(
                f"METRIC retry operation={operation} attempt={attempt} "
                f"delay={delay:.2f}s error={error} total_retries={count}"
            )

    def record_success(self, operation: str, elapsed: float):
        """Record a successful operation."""
        with self._lock:
            self._success_count += 1
            count = self._success_count
        if METRICS_ENABLED:
            logger.debug(
                f"METRIC success operation={operation} elapsed={elapsed:.2f}s "
                f"total_success={count}"
            )

    def record_error(self, operation: str, error: str, elapsed: float):
        """Record an error."""
        with self._lock:
            self._error_count += 1
            count = self._error_count
        if METRICS_ENABLED:
            logger.info(
                f"METRIC error operation={operation} error={error} "
                f"elapsed={elapsed:.2f}s total_errors={count}"
            )

    def get_stats(self) -> dict:
        """Get current metrics statistics."""
        with self._lock:
            return {
                "timeouts": self._timeout_count,
                "retries": self._retry_count,
                "successes": self._success_count,
                "errors": self._error_count,
            }

    def reset(self) -> None:
        """Reset all metrics counters to zero.

        Useful for testing and periodic metrics collection where counters
        are exported and then reset.
        """
        with self._lock:
            self._timeout_count = 0
            self._retry_count = 0
            self._success_count = 0
            self._error_count = 0


# Global metrics instance
metrics = Metrics()


# =============================================================================
# Logging Utilities
# =============================================================================

def sanitize_for_log(value: str, max_length: int = 200) -> str:
    """
    Sanitize user-controlled data for safe logging.

    Prevents log injection attacks by removing/escaping:
    - Newlines (could create fake log entries)
    - Carriage returns (same)
    - ANSI escape codes (could corrupt terminals/log viewers)

    Args:
        value: User-controlled string to sanitize
        max_length: Maximum length to prevent log bloat

    Returns:
        Sanitized string safe for logging
    """
    # Remove newlines and carriage returns
    sanitized = value.replace('\n', '\\n').replace('\r', '\\r')
    # Remove ANSI escape sequences (CSI sequences start with ESC[)
    sanitized = sanitized.replace('\x1b', '\\x1b')
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length - 3] + "..."
    return sanitized


# =============================================================================
# Retry Logic
# =============================================================================

# Exceptions that should trigger a retry (transient errors)
# TransientError is the base class for all transient errors in CatLoader
# Also includes Python built-in transient errors
RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    TransientError,  # Base class covers NetworkError, RateLimitError, ServerError
    ConnectionError,
    TimeoutError,
)


def calculate_backoff_delay(attempt: int) -> float:
    """
    Calculate delay for exponential backoff.

    Args:
        attempt: The current attempt number (0-indexed)

    Returns:
        Delay in seconds, capped at RETRY_MAX_DELAY
    """
    delay = RETRY_BASE_DELAY * (2 ** attempt)
    return min(delay, RETRY_MAX_DELAY)
