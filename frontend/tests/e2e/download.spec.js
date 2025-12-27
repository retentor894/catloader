import { test, expect } from '@playwright/test';
import { mockVideoInfo } from '../fixtures/mock-responses.js';

test.describe('Video/Audio Downloads', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');

    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(mockVideoInfo),
      });
    });

    await page.fill('#url-input', 'https://www.youtube.com/watch?v=test');
    await page.click('#search-btn');
    await expect(page.locator('#video-result')).toBeVisible();
  });

  test('should trigger download on video button click', async ({ page }) => {
    let downloadTriggered = false;
    let downloadUrl = '';

    await page.route('**/api/download*', async (route) => {
      downloadTriggered = true;
      downloadUrl = route.request().url();

      await route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'video/mp4',
          'Content-Disposition': 'attachment; filename="test_video.mp4"',
        },
        body: Buffer.from('fake video data'),
      });
    });

    await page.locator('#video-formats .format-btn').first().click();

    await page.waitForTimeout(500);

    expect(downloadTriggered).toBe(true);
    expect(downloadUrl).toContain('format_id=');
    expect(downloadUrl).toContain('audio_only=false');
  });

  test('should trigger audio download with correct parameters', async ({ page }) => {
    let downloadUrl = '';

    await page.route('**/api/download*', async (route) => {
      downloadUrl = route.request().url();
      await route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'audio/mpeg',
        },
        body: Buffer.from('fake audio data'),
      });
    });

    await page.locator('#audio-formats .format-btn').first().click();

    await page.waitForTimeout(500);

    expect(downloadUrl).toContain('format_id=140');
    expect(downloadUrl).toContain('audio_only=true');
  });

  test('should encode URL properly in download request', async ({ page }) => {
    let downloadUrl = '';

    await page.route('**/api/download*', async (route) => {
      downloadUrl = route.request().url();
      await route.fulfill({ status: 200, body: Buffer.from('data') });
    });

    await page.locator('#video-formats .format-btn').first().click();
    await page.waitForTimeout(200);

    // URL should be properly encoded
    expect(downloadUrl).toContain('url=https%3A%2F%2Fwww.youtube.com');
  });
});
