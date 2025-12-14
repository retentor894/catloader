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

  test('should show downloading state on button', async ({ page }) => {
    await page.route('**/api/download*', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 300));
      await route.fulfill({ status: 200, body: Buffer.from('data') });
    });

    const button = page.locator('#video-formats .format-btn').first();

    await button.click();

    await expect(button).toHaveClass(/downloading/);
    await expect(button).toContainText('Downloading...');

    // Should reset after delay
    await expect(button).not.toHaveClass(/downloading/, { timeout: 5000 });
  });

  test('should prevent multiple clicks on same button while downloading', async ({ page }) => {
    let requestCount = 0;

    await page.route('**/api/download*', async (route) => {
      requestCount++;
      await new Promise(resolve => setTimeout(resolve, 500));
      await route.fulfill({ status: 200, body: Buffer.from('data') });
    });

    const button = page.locator('#video-formats .format-btn').first();

    // Click multiple times rapidly
    await button.click();
    await button.click();
    await button.click();

    await page.waitForTimeout(200);

    // Should only trigger one download
    expect(requestCount).toBe(1);
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
