"""
Centralized configuration for CatLoader backend.

All settings can be overridden via environment variables.

Timeout Configuration
=====================
The timeout values are carefully coordinated across the stack:

    Frontend (95s) > Backend Info (90s) > yt-dlp socket (30s)

This ensures:
1. Backend always responds before frontend times out (5s buffer for network latency)
2. yt-dlp's internal socket_timeout limits how long orphaned threads run
3. Users receive meaningful error messages from the backend, not generic browser errors

Download timeout is longer (300s) because it includes the actual download which
varies greatly based on video size and network speed.
"""

import os

def _get_int_env(name: str, default: int) -> int:
    """Get integer from environment variable with default."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    """Get float from environment variable with default."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


# =============================================================================
# Timeout Configuration (seconds)
# =============================================================================

# Video info extraction timeout
# - Used by: /api/info endpoint
# - Should be less than frontend timeout (95s) to ensure backend error is received
# - yt-dlp's socket_timeout (30s) limits individual network operations
# - Env: CATLOADER_INFO_TIMEOUT
INFO_EXTRACTION_TIMEOUT = _get_int_env("CATLOADER_INFO_TIMEOUT", 90)

# Download initiation timeout
# - Used by: /api/download endpoint
# - Covers: URL validation, format selection, download start
# - Does NOT limit actual file transfer (streaming continues after this)
# - Longer than info timeout because download preparation is more complex
# - Env: CATLOADER_DOWNLOAD_TIMEOUT
DOWNLOAD_INIT_TIMEOUT = _get_int_env("CATLOADER_DOWNLOAD_TIMEOUT", 300)

# yt-dlp internal socket timeout (configured in downloader.py)
# - Limits individual HTTP operations within yt-dlp
# - Helps terminate orphaned threads after asyncio timeout
# - Env: CATLOADER_YTDLP_SOCKET_TIMEOUT
YTDLP_SOCKET_TIMEOUT = _get_int_env("CATLOADER_YTDLP_SOCKET_TIMEOUT", 30)

# =============================================================================
# Thread Pool Configuration
# =============================================================================

# Number of workers in the thread pool executor
# - Higher than typical because orphaned threads from timeouts may accumulate
# - yt-dlp operations are I/O bound, so more workers is generally fine
# - Env: CATLOADER_THREAD_POOL_WORKERS
THREAD_POOL_MAX_WORKERS = _get_int_env("CATLOADER_THREAD_POOL_WORKERS", 8)

# =============================================================================
# Retry Configuration
# =============================================================================

# Maximum number of retry attempts for transient errors (network issues, rate limits)
# - Env: CATLOADER_MAX_RETRIES
MAX_RETRIES = _get_int_env("CATLOADER_MAX_RETRIES", 3)

# Base delay for exponential backoff (seconds)
# - Actual delay: base_delay * (2 ^ attempt), e.g., 1s, 2s, 4s
# - Env: CATLOADER_RETRY_BASE_DELAY
RETRY_BASE_DELAY = _get_float_env("CATLOADER_RETRY_BASE_DELAY", 1.0)

# Maximum delay between retries (seconds)
# - Caps the exponential backoff to prevent excessive waits
# - Env: CATLOADER_RETRY_MAX_DELAY
RETRY_MAX_DELAY = _get_float_env("CATLOADER_RETRY_MAX_DELAY", 10.0)

# =============================================================================
# Metrics Configuration
# =============================================================================

# Enable metrics collection (logs timeout/retry statistics)
# - Env: CATLOADER_METRICS_ENABLED
METRICS_ENABLED = os.environ.get("CATLOADER_METRICS_ENABLED", "true").lower() == "true"

# =============================================================================
# URL Validation Pattern
# =============================================================================

import re

URL_PATTERN = re.compile(
    r'^https?://'  # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,}|'  # domain
    r'localhost|'  # or localhost
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IPv4
    r'(?::\d+)?'  # optional port
    r'(?:/?|[/?]\S+)$',  # path
    re.IGNORECASE
)


def validate_url(url: str) -> str:
    """
    Validate URL format and return cleaned URL.

    Args:
        url: The URL to validate

    Returns:
        The cleaned/trimmed URL

    Raises:
        ValueError: If URL is empty or invalid format
    """
    if not url or not url.strip():
        raise ValueError("URL cannot be empty")

    url = url.strip()
    if not URL_PATTERN.match(url):
        raise ValueError("Invalid URL format. URL must start with http:// or https://")

    return url
