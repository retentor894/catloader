"""Tests for utility functions including metrics and backoff calculation."""

import pytest
import threading

from app.utils import (
    Metrics,
    calculate_backoff_delay,
    RETRYABLE_EXCEPTIONS,
)


class TestMetrics:
    """Test Metrics class thread-safety and functionality."""

    def test_metrics_initialization(self):
        """Should initialize all counters to zero."""
        metrics = Metrics()
        stats = metrics.get_stats()
        assert stats["timeouts"] == 0
        assert stats["retries"] == 0
        assert stats["successes"] == 0
        assert stats["errors"] == 0

    def test_record_timeout_increments_counter(self):
        """Should increment timeout counter."""
        metrics = Metrics()
        metrics.record_timeout(endpoint="/api/info", elapsed=10.0)
        assert metrics.get_stats()["timeouts"] == 1

    def test_record_retry_increments_counter(self):
        """Should increment retry counter."""
        metrics = Metrics()
        metrics.record_retry(operation="test", attempt=1, delay=1.0, error="test error")
        assert metrics.get_stats()["retries"] == 1

    def test_record_success_increments_counter(self):
        """Should increment success counter."""
        metrics = Metrics()
        metrics.record_success(operation="test", elapsed=1.0)
        assert metrics.get_stats()["successes"] == 1

    def test_record_error_increments_counter(self):
        """Should increment error counter."""
        metrics = Metrics()
        metrics.record_error(operation="test", error="test error", elapsed=1.0)
        assert metrics.get_stats()["errors"] == 1

    def test_metrics_thread_safety(self):
        """Should handle concurrent updates safely."""
        metrics = Metrics()
        num_threads = 10
        increments_per_thread = 100

        def increment_all():
            for _ in range(increments_per_thread):
                metrics.record_timeout(endpoint="/test", elapsed=1.0)
                metrics.record_retry(operation="test", attempt=1, delay=0.1, error="e")
                metrics.record_success(operation="test", elapsed=1.0)
                metrics.record_error(operation="test", error="e", elapsed=1.0)

        threads = [threading.Thread(target=increment_all) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * increments_per_thread
        stats = metrics.get_stats()
        assert stats["timeouts"] == expected
        assert stats["retries"] == expected
        assert stats["successes"] == expected
        assert stats["errors"] == expected

    def test_reset_clears_all_counters(self):
        """Should reset all counters to zero."""
        metrics = Metrics()
        # Record some metrics
        metrics.record_timeout(endpoint="/test", elapsed=1.0)
        metrics.record_retry(operation="test", attempt=1, delay=0.1, error="e")
        metrics.record_success(operation="test", elapsed=1.0)
        metrics.record_error(operation="test", error="e", elapsed=1.0)

        # Verify non-zero
        stats = metrics.get_stats()
        assert stats["timeouts"] == 1
        assert stats["retries"] == 1

        # Reset and verify all zeros
        metrics.reset()
        stats = metrics.get_stats()
        assert stats["timeouts"] == 0
        assert stats["retries"] == 0
        assert stats["successes"] == 0
        assert stats["errors"] == 0


class TestCalculateBackoffDelay:
    """Test exponential backoff delay calculation."""

    def test_first_attempt_returns_base_delay(self):
        """Should return base delay for first attempt."""
        # Default RETRY_BASE_DELAY is 1.0
        delay = calculate_backoff_delay(0)
        assert delay == 1.0

    def test_exponential_increase(self):
        """Should double delay for each attempt."""
        delays = [calculate_backoff_delay(i) for i in range(4)]
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0
        assert delays[3] == 8.0

    def test_max_delay_cap(self):
        """Should cap delay at RETRY_MAX_DELAY."""
        # Default RETRY_MAX_DELAY is 10.0
        delay = calculate_backoff_delay(10)  # Would be 1024 without cap
        assert delay == 10.0
