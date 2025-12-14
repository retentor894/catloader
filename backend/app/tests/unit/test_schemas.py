import pytest
from pydantic import ValidationError
from app.models.schemas import URLRequest, VideoInfo, VideoFormat, ErrorResponse


class TestURLRequest:
    """Test URLRequest schema validation."""

    def test_valid_url(self):
        """Should accept valid URL."""
        request = URLRequest(url="https://www.youtube.com/watch?v=test")
        assert request.url == "https://www.youtube.com/watch?v=test"

    def test_url_with_special_chars(self):
        """Should accept URL with special characters."""
        request = URLRequest(url="https://youtube.com/watch?v=test&t=10s")
        assert "&t=10s" in request.url

    def test_missing_url_raises_error(self):
        """Should reject missing URL field."""
        with pytest.raises(ValidationError):
            URLRequest()

    def test_empty_url_raises_error(self):
        """Should reject empty URL."""
        with pytest.raises(ValidationError, match="URL cannot be empty"):
            URLRequest(url="")

    def test_whitespace_only_url_raises_error(self):
        """Should reject whitespace-only URL."""
        with pytest.raises(ValidationError, match="URL cannot be empty"):
            URLRequest(url="   ")

    def test_invalid_url_format_raises_error(self):
        """Should reject invalid URL format."""
        with pytest.raises(ValidationError, match="Invalid URL format"):
            URLRequest(url="not-a-url")

    def test_url_without_protocol_raises_error(self):
        """Should reject URL without http/https protocol."""
        with pytest.raises(ValidationError, match="Invalid URL format"):
            URLRequest(url="www.youtube.com/watch?v=test")

    def test_http_url_accepted(self):
        """Should accept http:// URLs."""
        request = URLRequest(url="http://example.com/video")
        assert request.url == "http://example.com/video"

    def test_localhost_url_accepted(self):
        """Should accept localhost URLs."""
        request = URLRequest(url="http://localhost:8000/api")
        assert request.url == "http://localhost:8000/api"

    def test_ip_address_url_accepted(self):
        """Should accept IP address URLs."""
        request = URLRequest(url="http://192.168.1.1:3000/video")
        assert request.url == "http://192.168.1.1:3000/video"

    def test_url_trimmed(self):
        """Should trim whitespace from URL."""
        request = URLRequest(url="  https://youtube.com/watch  ")
        assert request.url == "https://youtube.com/watch"


class TestVideoFormat:
    """Test VideoFormat schema."""

    def test_video_format_creation(self):
        """Should create video format with all fields."""
        fmt = VideoFormat(
            format_id="137",
            ext="mp4",
            resolution="1080p",
            filesize=50000000,
            has_audio=True,
            has_video=True,
            quality_label="1080p (MP4)"
        )
        assert fmt.format_id == "137"
        assert fmt.resolution == "1080p"
        assert fmt.has_audio is True
        assert fmt.filesize == 50000000

    def test_audio_format_creation(self):
        """Should create audio-only format."""
        fmt = VideoFormat(
            format_id="140",
            ext="m4a",
            resolution=None,
            has_audio=True,
            has_video=False,
            quality_label="128kbps (M4A)"
        )
        assert fmt.has_video is False
        assert fmt.resolution is None

    def test_optional_fields_default_values(self):
        """Should use default values for optional fields."""
        fmt = VideoFormat(format_id="best", ext="mp4")
        assert fmt.filesize is None
        assert fmt.quality_label is None
        assert fmt.has_audio is True
        assert fmt.has_video is True


class TestVideoInfo:
    """Test VideoInfo schema."""

    def test_complete_video_info(self):
        """Should create complete video info."""
        info = VideoInfo(
            title="Test Video",
            thumbnail="https://example.com/thumb.jpg",
            duration=300,
            uploader="Test Channel",
            video_formats=[
                VideoFormat(format_id="137", ext="mp4", resolution="1080p")
            ],
            audio_formats=[
                VideoFormat(format_id="140", ext="m4a", has_video=False)
            ]
        )
        assert info.title == "Test Video"
        assert info.duration == 300
        assert len(info.video_formats) == 1
        assert len(info.audio_formats) == 1

    def test_minimal_video_info(self):
        """Should create video info with only required fields."""
        info = VideoInfo(title="Test")
        assert info.title == "Test"
        assert info.thumbnail is None
        assert info.duration is None
        assert info.video_formats == []
        assert info.audio_formats == []

    def test_empty_formats_lists(self):
        """Should allow empty format lists."""
        info = VideoInfo(
            title="Test",
            video_formats=[],
            audio_formats=[]
        )
        assert info.video_formats == []
        assert info.audio_formats == []


class TestErrorResponse:
    """Test ErrorResponse schema."""

    def test_error_with_detail(self):
        """Should create error with detail."""
        error = ErrorResponse(error="Not found", detail="Video not available")
        assert error.error == "Not found"
        assert error.detail == "Video not available"

    def test_error_without_detail(self):
        """Should create error without detail."""
        error = ErrorResponse(error="Server error")
        assert error.error == "Server error"
        assert error.detail is None
