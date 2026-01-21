"""
Input validation utilities for CatLoader.

This module is separate from config.py to follow Single Responsibility Principle:
- config.py: configuration values only
- validation.py: validation logic
"""

import re

# URL validation pattern supporting:
# - HTTP and HTTPS protocols
# - Domain names (e.g., youtube.com)
# - localhost
# - IPv4 addresses (e.g., 192.168.1.1)
# - IPv6 addresses in brackets (e.g., [::1], [2001:db8::1])
# - Optional port numbers
# - Optional paths and query strings
#
# IPv6 LIMITATION: The regex uses a simplified pattern that covers common IPv6
# formats but is not fully RFC 5952 compliant. It accepts:
#   - [2001:db8::1], [::1], [fe80::1]
# But may incorrectly accept some invalid forms or reject edge cases like:
#   - Zone IDs (e.g., [fe80::1%eth0])
#   - IPv4-mapped addresses (e.g., [::ffff:192.0.2.1])
# This is acceptable for CatLoader's use case (video URLs from major platforms
# which use domain names, not raw IPv6 addresses).
#
# =============================================================================
# SECURITY WARNING: SSRF (Server-Side Request Forgery) Risk
# =============================================================================
# This pattern ALLOWS localhost and private IP addresses, which could enable
# SSRF attacks if the backend can make requests to internal network resources.
#
# An attacker could submit URLs like:
#   - http://localhost:8000/admin
#   - http://192.168.1.1/router-config
#   - http://[::1]:6379/  (Redis)
#   - http://169.254.169.254/latest/meta-data/  (AWS metadata service)
#
# This is ACCEPTABLE for CatLoader because:
# 1. yt-dlp only extracts video metadata/content, not arbitrary HTTP content
# 2. yt-dlp would fail on non-video URLs (no extractors match)
# 3. CatLoader is designed for trusted users (personal video downloads)
#
# For production deployments with untrusted users, consider:
# 1. Adding a blocklist for private IP ranges (10.x, 172.16-31.x, 192.168.x)
# 2. Adding a blocklist for localhost and link-local addresses
# 3. Using DNS resolution validation (resolve hostname, check if IP is private)
# 4. Running yt-dlp in a network-isolated container
# 5. Using an allowlist of permitted video hosting domains
#
# Example blocklist implementation (add to validate_url function):
#   import ipaddress
#   from urllib.parse import urlparse
#   hostname = urlparse(url).hostname
#   if hostname in ('localhost', '127.0.0.1', '::1'): raise ValueError(...)
#   try:
#       ip = ipaddress.ip_address(hostname)
#       if ip.is_private or ip.is_loopback: raise ValueError(...)
#   except ValueError: pass  # hostname is not an IP
# =============================================================================
URL_PATTERN = re.compile(
    r'^https?://'  # http:// or https://
    r'(?:'
    r'(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,}|'  # domain
    r'localhost|'  # or localhost
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'  # or IPv4
    r'\[(?:[A-F0-9]{0,4}:){2,7}[A-F0-9]{0,4}\]'  # or IPv6 in brackets (simplified)
    r')'
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


# Download ID validation pattern
# Download IDs are generated using secrets.token_urlsafe(32) which produces
# a URL-safe base64-encoded string of approximately 43 characters.
# We validate the format to prevent malformed IDs from being processed.
DOWNLOAD_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')
DOWNLOAD_ID_MIN_LENGTH = 40
DOWNLOAD_ID_MAX_LENGTH = 50


def validate_download_id(download_id: str) -> str:
    """
    Validate download ID format.

    Download IDs are generated using secrets.token_urlsafe(32), producing
    URL-safe base64 strings. This validation prevents processing of
    malformed or potentially malicious IDs.

    Args:
        download_id: The download ID to validate

    Returns:
        The validated download ID

    Raises:
        ValueError: If download_id is invalid
    """
    if not download_id:
        raise ValueError("Download ID cannot be empty")

    # Check length
    if len(download_id) < DOWNLOAD_ID_MIN_LENGTH or len(download_id) > DOWNLOAD_ID_MAX_LENGTH:
        raise ValueError(
            f"Invalid download ID length (expected {DOWNLOAD_ID_MIN_LENGTH}-{DOWNLOAD_ID_MAX_LENGTH} characters)"
        )

    # Check character set (URL-safe base64)
    if not DOWNLOAD_ID_PATTERN.match(download_id):
        raise ValueError("Invalid download ID format")

    return download_id


# yt-dlp format ID validation pattern
# Allows characters commonly used in yt-dlp format strings:
# - alphanumeric: a-z, A-Z, 0-9
# - format selectors: +, / (combine formats, fallback)
# - brackets and comparisons: [, ], <, >, =, !, : (format filtering)
# - other: -, _, . (format identifiers)
# Maximum length: 200 chars (reasonable limit for format strings)
#
# Examples of valid format strings:
#   - "best", "bestvideo+bestaudio", "137+140"
#   - "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
#   - "bestaudio[ext=m4a]/bestaudio"
FORMAT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9+/\-_.\[\]<>=!:]+$')
FORMAT_ID_MAX_LENGTH = 200


def validate_format_id(format_id: str) -> str:
    """
    Validate yt-dlp format ID string.

    Args:
        format_id: The format ID to validate

    Returns:
        The validated format ID

    Raises:
        ValueError: If format_id is invalid or contains disallowed characters
    """
    if not format_id:
        return "best"  # Default to best if empty

    format_id = format_id.strip()

    if len(format_id) > FORMAT_ID_MAX_LENGTH:
        raise ValueError(f"Format ID too long (max {FORMAT_ID_MAX_LENGTH} characters)")

    if not FORMAT_ID_PATTERN.match(format_id):
        raise ValueError(
            "Invalid format ID. Only alphanumeric characters and "
            "+/-_.[]<>=!: are allowed"
        )

    return format_id
