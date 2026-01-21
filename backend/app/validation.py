"""
URL validation utilities for CatLoader.

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
