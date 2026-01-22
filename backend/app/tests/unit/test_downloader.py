import pytest
import os
from unittest.mock import patch, MagicMock
from app.services.downloader import get_video_info, download_video
from app.models.schemas import VideoInfo
from app.exceptions import VideoExtractionError, DownloadError


class TestGetVideoInfo:
    """Test get_video_info function."""

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    def test_successful_info_extraction(self, mock_ydl_class, mock_yt_dlp_info):
        """Should extract video information successfully."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_yt_dlp_info
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        result = get_video_info("https://www.youtube.com/watch?v=test")

        assert isinstance(result, VideoInfo)
        assert result.title == "Test Video Title"
        assert result.duration == 300
        assert result.uploader == "Test Channel"
        assert len(result.video_formats) > 0
        assert len(result.audio_formats) > 0

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    def test_null_info_raises_error(self, mock_ydl_class):
        """Should raise error when yt-dlp returns None."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        with pytest.raises(VideoExtractionError, match="Could not extract video information"):
            get_video_info("https://invalid-url.com")

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    def test_network_error_propagates(self, mock_ydl_class):
        """Should propagate network errors from yt-dlp."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("Network error")
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        with pytest.raises(Exception, match="Network error"):
            get_video_info("https://www.youtube.com/watch?v=test")

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    def test_formats_sorted_by_quality(self, mock_ydl_class, mock_yt_dlp_info):
        """Should sort video formats by resolution (highest first)."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_yt_dlp_info
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        result = get_video_info("https://test.com")

        resolutions = [f.resolution for f in result.video_formats]
        # Should be sorted descending
        resolution_values = [int(r.replace('p', '')) for r in resolutions if r]
        assert resolution_values == sorted(resolution_values, reverse=True)

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    def test_fallback_formats_when_empty(self, mock_ydl_class, mock_yt_dlp_info_minimal):
        """Should provide fallback formats when none available."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_yt_dlp_info_minimal
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        result = get_video_info("https://test.com")

        assert len(result.video_formats) > 0
        assert len(result.audio_formats) > 0
        assert result.video_formats[0].format_id == 'bestvideo+bestaudio/best'
        assert result.audio_formats[0].format_id == 'bestaudio/best'

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    def test_audio_formats_sorted_by_bitrate(self, mock_ydl_class, mock_yt_dlp_info):
        """Should sort audio formats by bitrate (highest first)."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = mock_yt_dlp_info
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        result = get_video_info("https://test.com")

        # Extract bitrates from quality labels
        bitrates = []
        for f in result.audio_formats:
            if f.quality_label and 'kbps' in f.quality_label:
                bitrates.append(int(f.quality_label.split('kbps')[0]))

        assert bitrates == sorted(bitrates, reverse=True)


class TestDownloadVideo:
    """Test download_video function."""

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    @patch('app.services.downloader.tempfile.mkdtemp')
    def test_successful_video_download(self, mock_mkdtemp, mock_ydl_class,
                                        temp_download_dir, create_temp_file):
        """Should download video and return stream."""
        mock_mkdtemp.return_value = temp_download_dir
        create_temp_file("Test Video.mp4", b"video content" * 100)

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {'title': 'Test Video'}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        filename, content_type, file_size, stream = download_video(
            "https://test.com", "137", audio_only=False
        )

        assert filename == "Test Video.mp4"
        assert content_type == "video/mp4"
        assert file_size > 0
        # Consume stream
        chunks = list(stream)
        assert len(chunks) > 0

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    @patch('app.services.downloader.tempfile.mkdtemp')
    def test_audio_download_sets_postprocessors(self, mock_mkdtemp, mock_ydl_class,
                                                  temp_download_dir, create_temp_file):
        """Should configure FFmpeg postprocessor for audio-only downloads."""
        mock_mkdtemp.return_value = temp_download_dir
        create_temp_file("Test Audio.mp3", b"audio content")

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {'title': 'Test Audio'}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        download_video("https://test.com", "140", audio_only=True)

        # Verify postprocessors were set
        call_args = mock_ydl_class.call_args[0][0]
        assert 'postprocessors' in call_args
        assert call_args['postprocessors'][0]['key'] == 'FFmpegExtractAudio'
        assert call_args['postprocessors'][0]['preferredcodec'] == 'mp3'

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    @patch('app.services.downloader.tempfile.mkdtemp')
    def test_download_failure_raises_error(self, mock_mkdtemp, mock_ydl_class,
                                            temp_download_dir):
        """Should raise error when download fails."""
        mock_mkdtemp.return_value = temp_download_dir

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        with pytest.raises(DownloadError, match="Could not download video"):
            download_video("https://test.com", "best")

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    @patch('app.services.downloader.tempfile.mkdtemp')
    def test_file_not_found_raises_error(self, mock_mkdtemp, mock_ydl_class,
                                          temp_download_dir):
        """Should raise error when downloaded file is not found."""
        mock_mkdtemp.return_value = temp_download_dir
        # Don't create any file

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {'title': 'Test'}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        with pytest.raises(DownloadError, match="Download completed but file not found"):
            download_video("https://test.com", "best")

    def test_content_type_mp4(self):
        """Should detect video/mp4 content type."""
        import tempfile as tf
        temp_dir = tf.mkdtemp()

        filepath = os.path.join(temp_dir, "video.mp4")
        with open(filepath, 'wb') as f:
            f.write(b"content")

        with patch('app.services.downloader.tempfile.mkdtemp', return_value=temp_dir):
            with patch('app.services.downloader.yt_dlp.YoutubeDL') as mock_ydl_class:
                mock_ydl = MagicMock()
                mock_ydl.extract_info.return_value = {'title': 'Test'}
                mock_ydl_class.return_value.__enter__.return_value = mock_ydl

                _, content_type, _, stream = download_video("https://test.com", "best")
                list(stream)

                assert content_type == "video/mp4"

    def test_content_type_mp3(self):
        """Should detect audio/mpeg content type for mp3."""
        import tempfile as tf
        temp_dir = tf.mkdtemp()

        filepath = os.path.join(temp_dir, "audio.mp3")
        with open(filepath, 'wb') as f:
            f.write(b"content")

        with patch('app.services.downloader.tempfile.mkdtemp', return_value=temp_dir):
            with patch('app.services.downloader.yt_dlp.YoutubeDL') as mock_ydl_class:
                mock_ydl = MagicMock()
                mock_ydl.extract_info.return_value = {'title': 'Test'}
                mock_ydl_class.return_value.__enter__.return_value = mock_ydl

                _, content_type, _, stream = download_video("https://test.com", "best")
                list(stream)

                assert content_type == "audio/mpeg"

    def test_content_type_unknown(self):
        """Should use octet-stream for unknown extensions."""
        import tempfile as tf
        temp_dir = tf.mkdtemp()

        filepath = os.path.join(temp_dir, "file.xyz")
        with open(filepath, 'wb') as f:
            f.write(b"content")

        with patch('app.services.downloader.tempfile.mkdtemp', return_value=temp_dir):
            with patch('app.services.downloader.yt_dlp.YoutubeDL') as mock_ydl_class:
                mock_ydl = MagicMock()
                mock_ydl.extract_info.return_value = {'title': 'Test'}
                mock_ydl_class.return_value.__enter__.return_value = mock_ydl

                _, content_type, _, stream = download_video("https://test.com", "best")
                list(stream)

                assert content_type == "application/octet-stream"

    @patch('app.services.downloader.yt_dlp.YoutubeDL')
    @patch('app.services.downloader.tempfile.mkdtemp')
    def test_temp_file_cleanup_after_streaming(self, mock_mkdtemp, mock_ydl_class,
                                                temp_download_dir, create_temp_file):
        """Should cleanup temp files after streaming completes."""
        mock_mkdtemp.return_value = temp_download_dir
        filepath = create_temp_file("test.mp4", b"content")

        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {'title': 'Test'}
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        _, _, _, stream = download_video("https://test.com", "best")

        # File should exist before consuming stream
        assert os.path.exists(filepath)

        # Consume stream
        list(stream)

        # File should be deleted after streaming
        assert not os.path.exists(filepath)
