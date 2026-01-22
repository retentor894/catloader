"""Custom exceptions for the CatLoader application.

Exception Hierarchy:
===================
CatLoaderError (base)
├── PermanentError (do not retry)
│   ├── VideoExtractionError (invalid URL, unsupported site)
│   │   └── UnsupportedURLError
│   ├── DownloadError (file not available, format not found)
│   └── ContentError (video unavailable, geo-blocked, private)
│
└── TransientError (retry with backoff)
    ├── NetworkError (connection issues, DNS failures)
    ├── RateLimitError (429 errors, throttling)
    └── ServerError (500-level errors from upstream)
"""

import logging

logger = logging.getLogger(__name__)


class CatLoaderError(Exception):
    """Base exception for CatLoader."""
    pass


# =============================================================================
# Permanent Errors (do not retry - client/content issues)
# =============================================================================

class PermanentError(CatLoaderError):
    """Base for errors that should not be retried."""
    pass


class VideoExtractionError(PermanentError):
    """Error extracting video information (invalid URL or unsupported site)."""
    pass


class UnsupportedURLError(VideoExtractionError):
    """URL is not supported or invalid."""
    pass


class DownloadError(PermanentError):
    """Error during download process (format not available, etc.)."""
    pass


class ContentError(PermanentError):
    """Content is unavailable (geo-blocked, private, deleted)."""
    pass


class FileSizeLimitError(PermanentError):
    """File exceeds maximum allowed size."""
    pass


# =============================================================================
# Transient Errors (retry with exponential backoff)
# =============================================================================

class TransientError(CatLoaderError):
    """Base for errors that may succeed on retry."""
    pass


class NetworkError(TransientError):
    """Network-related error (connection issues, DNS failures)."""
    pass


class RateLimitError(TransientError):
    """Rate limit hit (429 errors, throttling)."""
    pass


class ServerError(TransientError):
    """Server-side error from upstream (500-level errors)."""
    pass
