"""
Utility functions for retry logic and metrics collection.
"""

import asyncio
import logging
import threading
import time
from functools import wraps
from typing import TypeVar, Callable, Type, Tuple

from .config import MAX_RETRIES, RETRY_BASE_DELAY, RETRY_MAX_DELAY, METRICS_ENABLED
from .exceptions import NetworkError

logger = logging.getLogger(__name__)

T = TypeVar('T')

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


# Global metrics instance
metrics = Metrics()


# =============================================================================
# Retry Logic
# =============================================================================

# Exceptions that should trigger a retry (transient errors)
RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    NetworkError,
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


def with_retry(
    max_retries: int = MAX_RETRIES,
    retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    operation_name: str = "operation",
):
    """
    Decorator that adds retry logic with exponential backoff.

    WARNING: This decorator is for SYNCHRONOUS functions only. It uses time.sleep()
    which will block the event loop if used with async code. For async functions,
    use with_retry_async() instead.

    Args:
        max_retries: Maximum number of retry attempts
        retryable_exceptions: Tuple of exception types that should trigger retry
        operation_name: Name for logging/metrics

    Usage:
        @with_retry(max_retries=3, operation_name="video_info")
        def get_video_info(url):  # sync function only!
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e

                    if attempt < max_retries:
                        delay = calculate_backoff_delay(attempt)
                        metrics.record_retry(
                            operation=operation_name,
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(e)[:100]
                        )
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {operation_name} "
                            f"after error: {e}. Waiting {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries} retries exhausted for {operation_name}. "
                            f"Last error: {e}"
                        )

            # All retries exhausted, raise the last exception
            raise last_exception

        return wrapper
    return decorator


async def with_retry_async(
    func: Callable[..., T],
    *args,
    max_retries: int = MAX_RETRIES,
    retryable_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    operation_name: str = "operation",
    **kwargs
) -> T:
    """
    Execute an async function with retry logic.

    Args:
        func: The async function to execute
        *args: Positional arguments for func
        max_retries: Maximum number of retry attempts
        retryable_exceptions: Tuple of exception types that should trigger retry
        operation_name: Name for logging/metrics
        **kwargs: Keyword arguments for func

    Returns:
        The result of func

    Raises:
        The last exception if all retries are exhausted
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retryable_exceptions as e:
            last_exception = e

            if attempt < max_retries:
                delay = calculate_backoff_delay(attempt)
                metrics.record_retry(
                    operation=operation_name,
                    attempt=attempt + 1,
                    delay=delay,
                    error=str(e)[:100]
                )
                logger.warning(
                    f"Retry {attempt + 1}/{max_retries} for {operation_name} "
                    f"after error: {e}. Waiting {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {max_retries} retries exhausted for {operation_name}. "
                    f"Last error: {e}"
                )

    # All retries exhausted, raise the last exception
    raise last_exception
