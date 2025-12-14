"""Custom exceptions for the CatLoader application."""

import logging

logger = logging.getLogger(__name__)


class CatLoaderError(Exception):
    """Base exception for CatLoader."""
    pass


class VideoExtractionError(CatLoaderError):
    """Error extracting video information (client error - invalid URL or unsupported site)."""
    pass


class DownloadError(CatLoaderError):
    """Error during download process."""
    pass


class UnsupportedURLError(VideoExtractionError):
    """URL is not supported or invalid."""
    pass


class NetworkError(CatLoaderError):
    """Network-related error (server error)."""
    pass
