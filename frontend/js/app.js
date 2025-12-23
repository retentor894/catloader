// API URL configuration
// Always use relative URL since nginx proxies /api to backend
// This works for: Docker, Cloudflare Tunnel, and any reverse proxy setup
const API_URL = '';

const elements = {
    urlInput: document.getElementById('url-input'),
    searchBtn: document.getElementById('search-btn'),
    btnText: document.querySelector('.btn-text'),
    btnLoader: document.querySelector('.btn-loader'),
    errorMessage: document.getElementById('error-message'),
    videoResult: document.getElementById('video-result'),
    videoThumbnail: document.getElementById('video-thumbnail'),
    videoDuration: document.getElementById('video-duration'),
    videoTitle: document.getElementById('video-title'),
    videoUploader: document.getElementById('video-uploader'),
    videoFormats: document.getElementById('video-formats'),
    audioFormats: document.getElementById('audio-formats'),
};

let currentVideoUrl = '';

function formatDuration(seconds) {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) {
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatFileSize(bytes) {
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return `${bytes.toFixed(1)} ${units[i]}`;
}

function showError(message) {
    elements.errorMessage.textContent = message;
    elements.errorMessage.classList.remove('hidden');
    elements.videoResult.classList.add('hidden');
}

function hideError() {
    elements.errorMessage.classList.add('hidden');
}

function setLoading(loading) {
    elements.searchBtn.disabled = loading;
    elements.btnText.classList.toggle('hidden', loading);
    elements.btnLoader.classList.toggle('hidden', !loading);
}

function createFormatButton(format, isAudio) {
    const btn = document.createElement('button');
    btn.className = `format-btn ${isAudio ? 'audio' : 'video'}`;

    let label = format.quality_label || format.resolution || 'Download';
    if (format.filesize) {
        label += ` (${formatFileSize(format.filesize)})`;
    }
    btn.textContent = label;

    btn.addEventListener('click', () => downloadFile(format.format_id, isAudio, btn));
    return btn;
}

async function downloadFile(formatId, audioOnly, button) {
    if (button.classList.contains('downloading')) return;

    button.classList.add('downloading');
    const originalText = button.textContent;
    button.textContent = 'Downloading...';

    try {
        const params = new URLSearchParams({
            url: currentVideoUrl,
            format_id: formatId,
            audio_only: audioOnly,
        });

        const downloadUrl = `${API_URL}/api/download?${params}`;

        // Create temporary link and trigger download
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        // Reset button after a delay
        setTimeout(() => {
            button.classList.remove('downloading');
            button.textContent = originalText;
        }, 2000);
    } catch (error) {
        button.classList.remove('downloading');
        button.textContent = originalText;
        showError('Download failed. Please try again.');
    }
}

function displayVideoInfo(info) {
    elements.videoThumbnail.src = info.thumbnail || '';
    elements.videoDuration.textContent = formatDuration(info.duration);
    elements.videoTitle.textContent = info.title;
    elements.videoUploader.textContent = info.uploader || '';

    // Clear previous formats
    elements.videoFormats.innerHTML = '';
    elements.audioFormats.innerHTML = '';

    // Add video format buttons
    info.video_formats.forEach(format => {
        elements.videoFormats.appendChild(createFormatButton(format, false));
    });

    // Add audio format buttons
    info.audio_formats.forEach(format => {
        elements.audioFormats.appendChild(createFormatButton(format, true));
    });

    elements.videoResult.classList.remove('hidden');
}

async function fetchVideoInfo() {
    const url = elements.urlInput.value.trim();

    if (!url) {
        showError('Please enter a video URL');
        return;
    }

    // Basic URL validation
    try {
        new URL(url);
    } catch {
        showError('Please enter a valid URL');
        return;
    }

    hideError();
    setLoading(true);
    elements.videoResult.classList.add('hidden');

    try {
        const response = await fetch(`${API_URL}/api/info`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to fetch video info');
        }

        currentVideoUrl = url;
        displayVideoInfo(data);
    } catch (error) {
        showError(error.message || 'Failed to fetch video information. Please check the URL and try again.');
    } finally {
        setLoading(false);
    }
}

// Event listeners
elements.searchBtn.addEventListener('click', fetchVideoInfo);

elements.urlInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        fetchVideoInfo();
    }
});

// Auto-paste from clipboard on focus (if empty)
elements.urlInput.addEventListener('focus', async () => {
    if (elements.urlInput.value === '' && navigator.clipboard?.readText) {
        try {
            const text = await navigator.clipboard.readText();
            if (text && text.startsWith('http')) {
                elements.urlInput.value = text;
            }
        } catch {
            // Clipboard access denied, ignore
        }
    }
});
