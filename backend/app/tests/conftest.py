import pytest
import tempfile
import os
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_yt_dlp_info():
    """Mock video info from yt-dlp."""
    return {
        'title': 'Test Video Title',
        'thumbnail': 'https://example.com/thumb.jpg',
        'duration': 300,
        'uploader': 'Test Channel',
        'formats': [
            {
                'format_id': '137',
                'ext': 'mp4',
                'height': 1080,
                'vcodec': 'avc1',
                'acodec': 'none',
                'filesize': 50000000,
            },
            {
                'format_id': '136',
                'ext': 'mp4',
                'height': 720,
                'vcodec': 'avc1',
                'acodec': 'none',
                'filesize': 30000000,
            },
            {
                'format_id': '135',
                'ext': 'mp4',
                'height': 480,
                'vcodec': 'avc1',
                'acodec': 'none',
                'filesize': 15000000,
            },
            {
                'format_id': '140',
                'ext': 'm4a',
                'height': None,
                'vcodec': 'none',
                'acodec': 'mp4a.40.2',
                'abr': 128,
                'filesize': 5000000,
            },
            {
                'format_id': '139',
                'ext': 'm4a',
                'height': None,
                'vcodec': 'none',
                'acodec': 'mp4a.40.2',
                'abr': 48,
                'filesize': 2000000,
            },
        ]
    }


@pytest.fixture
def mock_yt_dlp_info_minimal():
    """Minimal video info without formats."""
    return {
        'title': 'Minimal Video',
        'formats': []
    }


@pytest.fixture
def temp_download_dir():
    """Create temporary directory for download tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup (directory may already be deleted by the code under test)
    if os.path.exists(temp_dir):
        for file in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, file))
            except:
                pass
        try:
            os.rmdir(temp_dir)
        except:
            pass


@pytest.fixture
def create_temp_file(temp_download_dir):
    """Factory fixture to create temporary files."""
    def _create(filename: str, content: bytes = b'fake content'):
        filepath = os.path.join(temp_download_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(content)
        return filepath
    return _create


@pytest.fixture
def mock_ydl_class(mock_yt_dlp_info):
    """Create a mock YoutubeDL class."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_yt_dlp_info

    mock_class = MagicMock()
    mock_class.return_value.__enter__.return_value = mock_ydl
    mock_class.return_value.__exit__.return_value = None

    return mock_class
