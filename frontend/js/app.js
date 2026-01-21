// API URL configuration
// - Local dev (port 5500): direct backend access on port 8000
// - All other cases (Docker, Cloudflare Tunnel, reverse proxy): use relative URL
const API_URL = window.location.port === '5500' ? 'http://localhost:8000' : '';

// Timeout for video info extraction (ms)
// Must be slightly higher than backend timeout (90s) to ensure we receive backend's error response
// Backend timeout: 90s, Frontend timeout: 95s (5s buffer for network latency)
const INFO_FETCH_TIMEOUT = 95000;

// Unified error messages - keep in sync with backend and nginx
const ERROR_MESSAGES = {
    502: 'Backend service unavailable. Please try again later.',
    503: 'Server is temporarily overloaded. Please try again later.',
    504: 'Server timeout. The video may be too long or the server is busy. Please try again.',
    timeout: 'Request timed out. The video may be too long or the server is busy. Please try again.',
    default: 'An error occurred. Please try again later.',
};

// UI timing constants (ms)
const UI_TIMINGS = {
    IFRAME_CLEANUP_DELAY: 60000,      // Time to wait before removing download iframe (1 min)
    SUCCESS_RESET_DELAY: 2000,        // Delay before resetting button after successful download
    ERROR_RESET_DELAY: 3000,          // Delay before resetting button after error
};

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
    const container = document.createElement('div');
    container.className = 'format-btn-container';

    const btn = document.createElement('button');
    btn.className = `format-btn ${isAudio ? 'audio' : 'video'}`;

    let label = format.quality_label || format.resolution || 'Download';
    if (format.filesize) {
        label += ` (${formatFileSize(format.filesize)})`;
    }
    btn.textContent = label;
    btn.dataset.originalLabel = label;

    const progressBar = document.createElement('div');
    progressBar.className = 'progress-bar hidden';
    progressBar.innerHTML = '<div class="progress-fill"></div>';

    const progressText = document.createElement('span');
    progressText.className = 'progress-text hidden';

    btn.addEventListener('click', () => downloadFile(format.format_id, isAudio, container));

    container.appendChild(btn);
    container.appendChild(progressBar);
    container.appendChild(progressText);

    return container;
}

function formatSpeed(bytesPerSecond) {
    if (!bytesPerSecond) return '';
    return formatFileSize(bytesPerSecond) + '/s';
}

function formatEta(seconds) {
    if (!seconds || seconds < 0) return '';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
}

function downloadFile(formatId, audioOnly, container) {
    const btn = container.querySelector('.format-btn');
    const progressBar = container.querySelector('.progress-bar');
    const progressFill = container.querySelector('.progress-fill');
    const progressText = container.querySelector('.progress-text');

    // Prevent multiple clicks
    if (btn.classList.contains('downloading')) return;

    btn.classList.add('downloading');
    btn.textContent = 'Starting...';
    progressBar.classList.remove('hidden');
    progressText.classList.remove('hidden');

    const params = new URLSearchParams({
        url: currentVideoUrl,
        format_id: formatId,
        audio_only: audioOnly,
    });

    const eventSource = new EventSource(`${API_URL}/api/download/progress?${params}`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.status) {
            case 'downloading':
                const percent = data.percent || 0;
                progressFill.style.width = `${percent}%`;
                btn.textContent = `${percent.toFixed(1)}%`;

                let statusText = '';
                if (data.speed) {
                    statusText += formatSpeed(data.speed);
                }
                if (data.eta) {
                    statusText += statusText ? ` - ${formatEta(data.eta)}` : formatEta(data.eta);
                }
                progressText.textContent = statusText;
                break;

            case 'processing':
                progressFill.style.width = '100%';
                btn.textContent = data.message || 'Processing...';
                progressText.textContent = '';
                break;

            case 'complete':
                eventSource.close();
                btn.textContent = 'Done!';
                progressText.textContent = '';

                // Trigger file download
                const downloadUrl = `${API_URL}/api/download/file/${data.download_id}`;
                const iframe = document.createElement('iframe');
                iframe.style.display = 'none';
                iframe.src = downloadUrl;
                document.body.appendChild(iframe);
                setTimeout(() => document.body.removeChild(iframe), UI_TIMINGS.IFRAME_CLEANUP_DELAY);

                // Reset UI after delay
                setTimeout(() => {
                    btn.classList.remove('downloading');
                    btn.textContent = btn.dataset.originalLabel;
                    progressBar.classList.add('hidden');
                    progressText.classList.add('hidden');
                    progressFill.style.width = '0%';
                }, UI_TIMINGS.SUCCESS_RESET_DELAY);
                break;

            case 'error':
                eventSource.close();
                btn.textContent = 'Error';
                progressText.textContent = data.message || 'Download failed';
                progressBar.classList.add('hidden');

                setTimeout(() => {
                    btn.classList.remove('downloading');
                    btn.textContent = btn.dataset.originalLabel;
                    progressText.classList.add('hidden');
                }, UI_TIMINGS.ERROR_RESET_DELAY);
                break;

            case 'waiting':
                // Heartbeat, do nothing
                break;
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
        btn.textContent = 'Error';
        progressBar.classList.add('hidden');
        progressText.textContent = 'Connection lost';

        setTimeout(() => {
            btn.classList.remove('downloading');
            btn.textContent = btn.dataset.originalLabel;
            progressText.classList.add('hidden');
        }, UI_TIMINGS.ERROR_RESET_DELAY);
    };
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

    // Create abort controller for timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), INFO_FETCH_TIMEOUT);

    try {
        const response = await fetch(`${API_URL}/api/info`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url }),
            signal: controller.signal,
        });

        // Handle error responses - check Content-Type to detect HTML error pages
        if (!response.ok) {
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                // Server returned non-JSON (likely HTML error page from nginx)
                // Use unified error messages for known status codes
                const errorMessage = ERROR_MESSAGES[response.status] || ERROR_MESSAGES.default;
                throw new Error(errorMessage);
            }
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to fetch video info');
        }

        const data = await response.json();

        currentVideoUrl = url;
        displayVideoInfo(data);
    } catch (error) {
        if (error.name === 'AbortError') {
            showError(ERROR_MESSAGES.timeout);
        } else {
            showError(error.message || 'Failed to fetch video information. Please check the URL and try again.');
        }
    } finally {
        clearTimeout(timeoutId);
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
