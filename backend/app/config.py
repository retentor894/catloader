"""
Centralized configuration for CatLoader backend.

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

# =============================================================================
# Timeout Configuration (seconds)
# =============================================================================

# Video info extraction timeout
# - Used by: /api/info endpoint
# - Should be less than frontend timeout (95s) to ensure backend error is received
# - yt-dlp's socket_timeout (30s) limits individual network operations
INFO_EXTRACTION_TIMEOUT = 90

# Download initiation timeout
# - Used by: /api/download endpoint
# - Covers: URL validation, format selection, download start
# - Does NOT limit actual file transfer (streaming continues after this)
# - Longer than info timeout because download preparation is more complex
DOWNLOAD_INIT_TIMEOUT = 300

# yt-dlp internal socket timeout (configured in downloader.py)
# - Limits individual HTTP operations within yt-dlp
# - Helps terminate orphaned threads after asyncio timeout
YTDLP_SOCKET_TIMEOUT = 30

# =============================================================================
# Thread Pool Configuration
# =============================================================================

# Number of workers in the thread pool executor
# - Higher than typical because orphaned threads from timeouts may accumulate
# - yt-dlp operations are I/O bound, so more workers is generally fine
THREAD_POOL_MAX_WORKERS = 8

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
