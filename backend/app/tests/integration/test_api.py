import pytest
from unittest.mock import patch, MagicMock
from fastapi import status
from app.models.schemas import VideoInfo, VideoFormat
from app.exceptions import VideoExtractionError, DownloadError, NetworkError


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_root_endpoint(self, client):
        """Should return API status on root."""
        response = client.get("/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["message"] == "CatLoader API"
        assert data["status"] == "running"

    def test_health_endpoint(self, client):
        """Should return healthy status."""
        response = client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "healthy"


class TestVideoInfoEndpoint:
    """Test POST /api/info endpoint."""

    @patch('app.routes.download.get_video_info')
    def test_successful_info_request(self, mock_get_info, client):
        """Should return video info for valid URL."""
        mock_get_info.return_value = VideoInfo(
            title="Test Video",
            thumbnail="https://example.com/thumb.jpg",
            duration=300,
            uploader="Test Channel",
            video_formats=[
                VideoFormat(
                    format_id="137",
                    ext="mp4",
                    resolution="1080p",
                    has_audio=True,
                    has_video=True,
                    quality_label="1080p (MP4)"
                )
            ],
            audio_formats=[
                VideoFormat(
                    format_id="140",
                    ext="m4a",
                    has_audio=True,
                    has_video=False,
                    quality_label="128kbps (M4A)"
                )
            ]
        )

        response = client.post(
            "/api/info",
            json={"url": "https://www.youtube.com/watch?v=test"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["title"] == "Test Video"
        assert data["duration"] == 300
        assert len(data["video_formats"]) == 1
        assert len(data["audio_formats"]) == 1

    def test_missing_url_field(self, client):
        """Should return 422 for missing URL."""
        response = client.post("/api/info", json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_invalid_json_body(self, client):
        """Should return 422 for invalid JSON."""
        response = client.post(
            "/api/info",
            content="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('app.routes.download.get_video_info')
    def test_video_extraction_error(self, mock_get_info, client):
        """Should return 400 when video extraction fails."""
        mock_get_info.side_effect = VideoExtractionError("Unsupported URL")

        response = client.post(
            "/api/info",
            json={"url": "https://unsupported-site.com/video"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "detail" in response.json()

    @patch('app.routes.download.get_video_info')
    def test_network_error_returns_503(self, mock_get_info, client):
        """Should return 503 for network errors."""
        mock_get_info.side_effect = NetworkError("Connection timeout")

        response = client.post(
            "/api/info",
            json={"url": "https://www.youtube.com/watch?v=test"}
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "detail" in response.json()

    @patch('app.routes.download.get_video_info')
    def test_unexpected_error_returns_500(self, mock_get_info, client):
        """Should return 500 for unexpected errors."""
        mock_get_info.side_effect = RuntimeError("Unexpected error")

        response = client.post(
            "/api/info",
            json={"url": "https://www.youtube.com/watch?v=test"}
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "detail" in response.json()

    @patch('app.routes.download.get_video_info')
    def test_response_contains_required_fields(self, mock_get_info, client):
        """Should return response with all required fields."""
        mock_get_info.return_value = VideoInfo(
            title="Test",
            video_formats=[],
            audio_formats=[]
        )

        response = client.post(
            "/api/info",
            json={"url": "https://test.com"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "title" in data
        assert "thumbnail" in data
        assert "duration" in data
        assert "uploader" in data
        assert "video_formats" in data
        assert "audio_formats" in data


class TestDownloadEndpoint:
    """Test GET /api/download endpoint."""

    @patch('app.routes.download.download_video')
    def test_successful_video_download(self, mock_download, client):
        """Should stream video file successfully."""
        def fake_generator():
            yield b"chunk1"
            yield b"chunk2"

        mock_download.return_value = (
            "Test Video.mp4",
            "video/mp4",
            12,  # file_size
            fake_generator()
        )

        response = client.get(
            "/api/download",
            params={
                "url": "https://www.youtube.com/watch?v=test",
                "format_id": "137",
                "audio_only": "false"
            }
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "video/mp4"
        assert "Content-Disposition" in response.headers
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.content == b"chunk1chunk2"

    @patch('app.routes.download.download_video')
    def test_successful_audio_download(self, mock_download, client):
        """Should stream audio file with correct content type."""
        def fake_generator():
            yield b"audio_data"

        mock_download.return_value = (
            "Test Audio.mp3",
            "audio/mpeg",
            10,  # file_size
            fake_generator()
        )

        response = client.get(
            "/api/download",
            params={
                "url": "https://www.youtube.com/watch?v=test",
                "format_id": "140",
                "audio_only": "true"
            }
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "audio/mpeg"

    def test_missing_url_parameter(self, client):
        """Should return 422 for missing URL parameter."""
        response = client.get("/api/download")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch('app.routes.download.download_video')
    def test_default_parameters(self, mock_download, client):
        """Should use default values for optional parameters."""
        def fake_generator():
            yield b"data"

        mock_download.return_value = ("video.mp4", "video/mp4", 4, fake_generator())

        response = client.get(
            "/api/download",
            params={"url": "https://test.com"}
        )

        assert response.status_code == status.HTTP_200_OK
        mock_download.assert_called_once_with("https://test.com", "best", False)

    @patch('app.routes.download.download_video')
    def test_url_passed_correctly(self, mock_download, client):
        """Should pass URL correctly to download function (FastAPI handles decoding)."""
        def fake_generator():
            yield b"data"

        mock_download.return_value = ("video.mp4", "video/mp4", 4, fake_generator())

        # Pass URL directly - FastAPI/test client handles encoding/decoding
        response = client.get(
            "/api/download",
            params={
                "url": "https://www.youtube.com/watch?v=test",
                "format_id": "best"
            }
        )

        assert response.status_code == status.HTTP_200_OK
        # Verify URL was passed correctly
        mock_download.assert_called_once()
        called_url = mock_download.call_args[0][0]
        assert called_url == "https://www.youtube.com/watch?v=test"

    @patch('app.routes.download.download_video')
    def test_unicode_filename_sanitization(self, mock_download, client):
        """Should sanitize non-ASCII characters in filename."""
        def fake_generator():
            yield b"data"

        mock_download.return_value = (
            "Video con acentos y caracteres",
            "video/mp4",
            4,  # file_size
            fake_generator()
        )

        response = client.get(
            "/api/download",
            params={"url": "https://test.com"}
        )

        assert response.status_code == status.HTTP_200_OK
        content_disp = response.headers["Content-Disposition"]
        # Should be valid ASCII
        content_disp.encode('ascii')

    @patch('app.routes.download.download_video')
    def test_fallback_filename_for_unicode_only(self, mock_download, client):
        """Should use fallback filename when original is only unicode."""
        def fake_generator():
            yield b"data"

        mock_download.return_value = (
            "\u4e2d\u6587\u6587\u4ef6",  # Chinese characters only
            "video/mp4",
            4,  # file_size
            fake_generator()
        )

        response = client.get(
            "/api/download",
            params={"url": "https://test.com", "audio_only": "false"}
        )

        assert response.status_code == status.HTTP_200_OK
        content_disp = response.headers["Content-Disposition"]
        assert "download.mp4" in content_disp

    @patch('app.routes.download.download_video')
    def test_download_failure(self, mock_download, client):
        """Should return 400 when download fails."""
        mock_download.side_effect = DownloadError("Download failed: 403 Forbidden")

        response = client.get(
            "/api/download",
            params={"url": "https://test.com"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "detail" in response.json()
        assert "403" in response.json()["detail"]

    @patch('app.routes.download.download_video')
    def test_download_network_error_returns_503(self, mock_download, client):
        """Should return 503 for network errors during download."""
        mock_download.side_effect = NetworkError("Connection reset")

        response = client.get(
            "/api/download",
            params={"url": "https://test.com"}
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "detail" in response.json()

    @patch('app.routes.download.download_video')
    def test_cache_control_header(self, mock_download, client):
        """Should include no-cache header."""
        def fake_generator():
            yield b"data"

        mock_download.return_value = ("video.mp4", "video/mp4", 4, fake_generator())

        response = client.get(
            "/api/download",
            params={"url": "https://test.com"}
        )

        assert response.headers["Cache-Control"] == "no-cache"


class TestTimeoutBehavior:
    """Test timeout handling for long-running operations."""

    @patch('app.routes.download.run_with_timeout')
    def test_info_timeout_returns_504(self, mock_run_with_timeout, client):
        """Should return 504 when video info extraction times out."""
        import asyncio
        mock_run_with_timeout.side_effect = asyncio.TimeoutError()

        response = client.post(
            "/api/info",
            json={"url": "https://www.youtube.com/watch?v=verylongvideo"}
        )

        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = response.json()
        assert "detail" in data
        assert "timed out" in data["detail"].lower()

    @patch('app.routes.download.run_with_timeout')
    def test_download_timeout_returns_504(self, mock_run_with_timeout, client):
        """Should return 504 when download times out."""
        import asyncio
        mock_run_with_timeout.side_effect = asyncio.TimeoutError()

        response = client.get(
            "/api/download",
            params={"url": "https://www.youtube.com/watch?v=verylargefile"}
        )

        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = response.json()
        assert "detail" in data
        assert "timed out" in data["detail"].lower()

    @patch('app.routes.download.run_with_timeout')
    def test_info_timeout_error_message(self, mock_run_with_timeout, client):
        """Should return helpful error message on info timeout."""
        import asyncio
        mock_run_with_timeout.side_effect = asyncio.TimeoutError()

        response = client.post(
            "/api/info",
            json={"url": "https://test.com/video"}
        )

        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = response.json()
        # Verify the message is helpful
        assert "video" in data["detail"].lower() or "server" in data["detail"].lower()
        assert "try again" in data["detail"].lower()

    @patch('app.routes.download.run_with_timeout')
    def test_download_timeout_error_message(self, mock_run_with_timeout, client):
        """Should return helpful error message on download timeout."""
        import asyncio
        mock_run_with_timeout.side_effect = asyncio.TimeoutError()

        response = client.get(
            "/api/download",
            params={"url": "https://test.com/video"}
        )

        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = response.json()
        # Verify the message is helpful
        assert "video" in data["detail"].lower() or "server" in data["detail"].lower() or "download" in data["detail"].lower()
        assert "try again" in data["detail"].lower()
