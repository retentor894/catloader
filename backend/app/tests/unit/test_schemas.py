import pytest
from pydantic import ValidationError
from app.models.schemas import URLRequest, VideoInfo, VideoFormat, ErrorResponse
from app.validation import validate_format_id, validate_download_id


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

    def test_ipv6_address_url_accepted(self):
        """Should accept IPv6 address URLs in brackets."""
        request = URLRequest(url="http://[::1]:8000/video")
        assert request.url == "http://[::1]:8000/video"

    def test_ipv6_full_address_url_accepted(self):
        """Should accept full IPv6 address URLs."""
        request = URLRequest(url="https://[2001:db8::1]/path")
        assert request.url == "https://[2001:db8::1]/path"

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
    """Test ErrorResponse schema matching FastAPI HTTPException format."""

    def test_error_response_creation(self):
        """Should create error response with detail."""
        error = ErrorResponse(detail="Video not available")
        assert error.detail == "Video not available"

    def test_error_response_matches_http_exception(self):
        """Should match FastAPI's HTTPException format."""
        # HTTPException returns {"detail": "..."} so ErrorResponse should match
        error = ErrorResponse(detail="Server timeout")
        assert error.model_dump() == {"detail": "Server timeout"}


class TestFormatIdValidation:
    """Test format_id validation for yt-dlp format strings."""

    def test_valid_simple_format(self):
        """Should accept simple format IDs."""
        assert validate_format_id("best") == "best"
        assert validate_format_id("137") == "137"
        assert validate_format_id("bestvideo") == "bestvideo"
        assert validate_format_id("bestaudio") == "bestaudio"

    def test_valid_combined_format(self):
        """Should accept combined format strings with + and /."""
        assert validate_format_id("bestvideo+bestaudio") == "bestvideo+bestaudio"
        assert validate_format_id("137+140") == "137+140"
        assert validate_format_id("bestaudio/best") == "bestaudio/best"

    def test_valid_format_with_filters(self):
        """Should accept format strings with filter expressions."""
        assert validate_format_id("bestvideo[height<=1080]") == "bestvideo[height<=1080]"
        assert validate_format_id("bestaudio[ext=m4a]") == "bestaudio[ext=m4a]"
        assert validate_format_id("best[height<=720]/best") == "best[height<=720]/best"

    def test_valid_complex_format(self):
        """Should accept complex format strings."""
        fmt = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        assert validate_format_id(fmt) == fmt

    def test_empty_format_returns_best(self):
        """Should return 'best' for empty format ID."""
        assert validate_format_id("") == "best"
        assert validate_format_id(None) == "best"

    def test_whitespace_trimmed(self):
        """Should trim whitespace from format ID."""
        assert validate_format_id("  best  ") == "best"

    def test_invalid_chars_rejected(self):
        """Should reject format IDs with invalid characters."""
        with pytest.raises(ValueError, match="Invalid format ID"):
            validate_format_id("best;rm -rf /")
        with pytest.raises(ValueError, match="Invalid format ID"):
            validate_format_id("best$(whoami)")
        with pytest.raises(ValueError, match="Invalid format ID"):
            validate_format_id("best`id`")
        with pytest.raises(ValueError, match="Invalid format ID"):
            validate_format_id("best|cat /etc/passwd")

    def test_too_long_format_rejected(self):
        """Should reject format IDs exceeding max length."""
        long_format = "a" * 201
        with pytest.raises(ValueError, match="too long"):
            validate_format_id(long_format)


class TestDownloadIdValidation:
    """Test download_id validation for secure token format."""

    def test_valid_download_id(self):
        """Should accept valid download IDs (URL-safe base64, ~43 chars)."""
        # secrets.token_urlsafe(32) generates ~43 character strings
        valid_id = "abcdefghijklmnopqrstuvwxyz1234567890_-ABCD"
        assert validate_download_id(valid_id) == valid_id

    def test_valid_download_id_with_underscores_dashes(self):
        """Should accept IDs with URL-safe characters (-, _)."""
        valid_id = "abc-def_ghi-jkl_mno-pqr_stu-vwx_yz12-345"  # 41 chars
        assert validate_download_id(valid_id) == valid_id

    def test_empty_download_id_rejected(self):
        """Should reject empty download ID."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_download_id("")
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_download_id(None)

    def test_too_short_download_id_rejected(self):
        """Should reject download IDs that are too short."""
        short_id = "a" * 39  # Less than minimum (40)
        with pytest.raises(ValueError, match="Invalid download ID length"):
            validate_download_id(short_id)

    def test_too_long_download_id_rejected(self):
        """Should reject download IDs that are too long."""
        long_id = "a" * 51  # More than maximum (50)
        with pytest.raises(ValueError, match="Invalid download ID length"):
            validate_download_id(long_id)

    def test_invalid_chars_rejected(self):
        """Should reject download IDs with invalid characters."""
        # 43 chars but with invalid characters
        with pytest.raises(ValueError, match="Invalid download ID format"):
            validate_download_id("abcdefghijklmnopqrstuvwxyz1234567890!@#$%")
        with pytest.raises(ValueError, match="Invalid download ID format"):
            validate_download_id("abcdefghijklmnopqrstuvwxyz1234567890/../..")
        with pytest.raises(ValueError, match="Invalid download ID format"):
            validate_download_id("abcdefghijklmnopqrstuvwxyz123456789 space")

    def test_path_traversal_rejected(self):
        """Should reject path traversal attempts."""
        with pytest.raises(ValueError, match="Invalid download ID format"):
            validate_download_id("../../etc/passwd" + "a" * 28)

    def test_minimum_valid_length(self):
        """Should accept download IDs at minimum length."""
        min_id = "a" * 40  # Exactly minimum
        assert validate_download_id(min_id) == min_id

    def test_maximum_valid_length(self):
        """Should accept download IDs at maximum length."""
        max_id = "a" * 50  # Exactly maximum
        assert validate_download_id(max_id) == max_id
