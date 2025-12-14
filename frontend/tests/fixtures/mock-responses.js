export const mockVideoInfo = {
  title: "Test Video - Playwright E2E Test",
  thumbnail: "https://via.placeholder.com/640x360",
  duration: 305,
  uploader: "Test Channel",
  video_formats: [
    {
      format_id: "bestvideo[height<=1080]+bestaudio",
      ext: "mp4",
      resolution: "1080p",
      filesize: 52428800,
      has_audio: true,
      has_video: true,
      quality_label: "1080p (MP4)"
    },
    {
      format_id: "bestvideo[height<=720]+bestaudio",
      ext: "mp4",
      resolution: "720p",
      filesize: 31457280,
      has_audio: true,
      has_video: true,
      quality_label: "720p (MP4)"
    },
    {
      format_id: "bestvideo[height<=480]+bestaudio",
      ext: "mp4",
      resolution: "480p",
      filesize: 15728640,
      has_audio: true,
      has_video: true,
      quality_label: "480p (MP4)"
    }
  ],
  audio_formats: [
    {
      format_id: "140",
      ext: "m4a",
      resolution: null,
      filesize: 5242880,
      has_audio: true,
      has_video: false,
      quality_label: "128kbps (M4A)"
    },
    {
      format_id: "139",
      ext: "m4a",
      resolution: null,
      filesize: 2621440,
      has_audio: true,
      has_video: false,
      quality_label: "48kbps (M4A)"
    }
  ]
};

export const mockErrorResponse = {
  detail: "Unsupported URL or video not available"
};
