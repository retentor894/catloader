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

IMPORTANT - Frontend Synchronization:
=====================================
If you change INFO_EXTRACTION_TIMEOUT, you MUST also update the frontend:
  - File: frontend/js/app.js
  - Constant: INFO_FETCH_TIMEOUT (should be INFO_EXTRACTION_TIMEOUT + 5000ms)

This coordination is necessary because frontend and backend cannot share code.
The frontend timeout must be higher to receive the backend's error message
rather than a generic browser timeout error.
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

# SSE progress stream timeout
# - Used by: /api/download/progress endpoint
# - Maximum time an SSE connection can stay open
# - Prevents indefinitely open connections
# - Env: CATLOADER_SSE_TIMEOUT
SSE_STREAM_TIMEOUT = _get_int_env("CATLOADER_SSE_TIMEOUT", 600)  # 10 minutes

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

# Maximum concurrent yt-dlp operations
# - Prevents thread pool exhaustion when many timeouts occur
# - Should be less than THREAD_POOL_MAX_WORKERS to leave headroom
# - When limit is reached, new requests get HTTP 503 immediately
# - Env: CATLOADER_MAX_CONCURRENT_OPS
MAX_CONCURRENT_OPERATIONS = _get_int_env("CATLOADER_MAX_CONCURRENT_OPS", 6)

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
# Download Limits
# =============================================================================

# Maximum file size allowed for download (bytes)
# - Prevents disk exhaustion from very large files
# - Default: 2GB (2147483648 bytes)
# - Set to 0 to disable limit
# - Env: CATLOADER_MAX_FILE_SIZE
MAX_FILE_SIZE = _get_int_env("CATLOADER_MAX_FILE_SIZE", 2 * 1024 * 1024 * 1024)  # 2GB

# Maximum URL length allowed (characters)
# - Prevents memory exhaustion from crafted long URLs
# - Most browsers limit URLs to 2048-8192 characters
# - Env: CATLOADER_MAX_URL_LENGTH
MAX_URL_LENGTH = _get_int_env("CATLOADER_MAX_URL_LENGTH", 2048)

# =============================================================================
# Downloader Configuration
# =============================================================================

# How long completed downloads are kept before cleanup (seconds)
# - Env: CATLOADER_DOWNLOAD_EXPIRY
DOWNLOAD_EXPIRY_SECONDS = _get_int_env("CATLOADER_DOWNLOAD_EXPIRY", 300)  # 5 minutes

# Maximum completed downloads to keep in memory
# - When limit is reached, oldest downloads are evicted
# - Env: CATLOADER_MAX_DOWNLOADS
MAX_COMPLETED_DOWNLOADS = _get_int_env("CATLOADER_MAX_DOWNLOADS", 100)

# Chunk size for streaming file downloads (bytes)
# - Env: CATLOADER_CHUNK_SIZE
CHUNK_SIZE = _get_int_env("CATLOADER_CHUNK_SIZE", 8192)

# Age threshold for cleaning orphaned temp directories (seconds)
# - Directories older than this are considered abandoned and cleaned up
# - Env: CATLOADER_ORPHAN_CLEANUP_AGE
ORPHAN_CLEANUP_AGE_SECONDS = _get_int_env("CATLOADER_ORPHAN_CLEANUP_AGE", 3600)  # 1 hour

# Prefix for temporary directories (used to identify orphans)
TEMP_DIR_PREFIX = "catloader_"

# User-Agent for yt-dlp HTTP requests
# - Some sites block requests without a browser-like User-Agent
# - Update periodically to match current browser versions
# - Env: CATLOADER_USER_AGENT
YTDLP_USER_AGENT = os.environ.get(
    "CATLOADER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Interval between SSE progress updates (seconds)
# - Lower values give more responsive UI but increase server load
# - Higher values reduce load but make progress appear to update in chunks
# - Env: CATLOADER_PROGRESS_POLL_INTERVAL
PROGRESS_POLL_INTERVAL = _get_float_env("CATLOADER_PROGRESS_POLL_INTERVAL", 0.5)

# =============================================================================
# Metrics Configuration
# =============================================================================

# Enable metrics collection (logs timeout/retry statistics)
# - Env: CATLOADER_METRICS_ENABLED
METRICS_ENABLED = os.environ.get("CATLOADER_METRICS_ENABLED", "true").lower() == "true"

# Note: URL validation has been moved to validation.py (SRP)

# =============================================================================
# Security Considerations (for production deployment)
# =============================================================================
#
# RATE LIMITING (IMPORTANT):
# --------------------------
# The internal semaphore (MAX_CONCURRENT_OPERATIONS) provides basic protection
# against thread pool exhaustion, but it does NOT protect against DoS attacks.
#
# For production deployments, implement rate limiting at the reverse proxy level:
#
# Nginx example:
#   limit_req_zone $binary_remote_addr zone=catloader:10m rate=10r/m;
#   location /api/ {
#       limit_req zone=catloader burst=5 nodelay;
#       proxy_pass http://backend:8000;
#   }
#
# This limits each IP to 10 requests per minute with a burst of 5.
#
# DOWNLOAD ID SECURITY:
# ---------------------
# Download IDs use cryptographically secure tokens (secrets.token_urlsafe with
# 256 bits of entropy), making them effectively unguessable. However, the
# download endpoint should still only be exposed to authenticated users in
# production environments where security is critical.
#
# HEALTH ENDPOINT SECURITY:
# -------------------------
# The /health/detailed endpoint exposes operational information that could
# help attackers (thread pool stats, disk usage, yt-dlp version, error counts).
#
# Restrict access to internal networks in production:
#   location /health/detailed {
#       allow 10.0.0.0/8;
#       allow 172.16.0.0/12;
#       allow 192.168.0.0/16;
#       deny all;
#       proxy_pass http://backend:8000;
#   }
#
# The basic /health endpoint is safe for public access (load balancer checks).
#
# CIRCUIT BREAKER (future enhancement):
# -------------------------------------
# For high-availability deployments, consider implementing a circuit breaker
# pattern to handle upstream failures (YouTube, Vimeo, etc.) gracefully.
#
# When an upstream service fails repeatedly:
# 1. Open the circuit (reject requests immediately with 503)
# 2. Wait for a cooldown period
# 3. Allow a test request through (half-open state)
# 4. If successful, close the circuit; if failed, keep it open
#
# Libraries to consider:
# - pybreaker: https://github.com/danielfm/pybreaker
# - aiobreaker: https://github.com/arlyon/aiobreaker (async-compatible)
#
# This would prevent resource exhaustion when upstream services are down
# and provide faster failure responses to users.
