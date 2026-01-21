import { test, expect } from '@playwright/test';
import { mockVideoInfo } from '../fixtures/mock-responses.js';

test.describe('Video/Audio Downloads', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');

    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockVideoInfo),
      });
    });

    await page.fill('#url-input', 'https://www.youtube.com/watch?v=test');
    await page.click('#search-btn');
    await expect(page.locator('#video-result')).toBeVisible();
  });

  test('should trigger download on video button click', async ({ page }) => {
    let progressUrl = '';
    let fileDownloadTriggered = false;

    // Mock SSE progress endpoint
    await page.route('**/api/download/progress*', async (route) => {
      progressUrl = route.request().url();
      const sseResponse =
        'data: {"status": "downloading", "percent": 50}\n\n' +
        'data: {"status": "complete", "download_id": "test-123", "filename": "test.mp4"}\n\n';

      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: sseResponse,
      });
    });

    // Mock file download endpoint
    await page.route('**/api/download/file/*', async (route) => {
      fileDownloadTriggered = true;
      await route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'video/mp4',
          'Content-Disposition': 'attachment; filename="test.mp4"',
        },
        body: Buffer.from('fake video data'),
      });
    });

    await page.locator('#video-formats .format-btn').first().click();
    await page.waitForTimeout(1000);

    expect(progressUrl).toContain('format_id=');
    expect(progressUrl).toContain('audio_only=false');
  });

  test('should trigger audio download with correct parameters', async ({ page }) => {
    let progressUrl = '';

    // Mock SSE progress endpoint
    await page.route('**/api/download/progress*', async (route) => {
      progressUrl = route.request().url();
      const sseResponse =
        'data: {"status": "complete", "download_id": "test-456", "filename": "test.mp3"}\n\n';

      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: sseResponse,
      });
    });

    await page.route('**/api/download/file/*', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'audio/mpeg' },
        body: Buffer.from('fake audio data'),
      });
    });

    await page.locator('#audio-formats .format-btn').first().click();
    await page.waitForTimeout(1000);

    expect(progressUrl).toContain('format_id=140');
    expect(progressUrl).toContain('audio_only=true');
  });

  test('should encode URL properly in download request', async ({ page }) => {
    let progressUrl = '';

    await page.route('**/api/download/progress*', async (route) => {
      progressUrl = route.request().url();
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        body: 'data: {"status": "complete", "download_id": "test-789"}\n\n',
      });
    });

    await page.route('**/api/download/file/*', async (route) => {
      await route.fulfill({ status: 200, body: Buffer.from('data') });
    });

    await page.locator('#video-formats .format-btn').first().click();
    await page.waitForTimeout(500);

    // URL should be properly encoded in the progress request
    expect(progressUrl).toContain('url=https%3A%2F%2Fwww.youtube.com');
  });
});
