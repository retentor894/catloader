import { test, expect } from '@playwright/test';
import { mockVideoInfo, mockErrorResponse } from '../fixtures/mock-responses.js';

test.describe('Video Information Fetching', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should display initial UI correctly', async ({ page }) => {
    await expect(page.locator('#url-input')).toBeVisible();
    await expect(page.locator('#search-btn')).toBeVisible();
    await expect(page.locator('#search-btn')).toContainText('Get Video');
    await expect(page.locator('#video-result')).toBeHidden();
    await expect(page.locator('#error-message')).toBeHidden();
  });

  test('should show error for empty URL', async ({ page }) => {
    await page.click('#search-btn');

    await expect(page.locator('#error-message')).toBeVisible();
    await expect(page.locator('#error-message')).toContainText('Please enter a video URL');
  });

  test('should show error for invalid URL', async ({ page }) => {
    await page.fill('#url-input', 'not-a-valid-url');
    await page.click('#search-btn');

    await expect(page.locator('#error-message')).toBeVisible();
    await expect(page.locator('#error-message')).toContainText('Please enter a valid URL');
  });

  test('should fetch and display video info successfully', async ({ page }) => {
    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockVideoInfo),
      });
    });

    await page.fill('#url-input', 'https://www.youtube.com/watch?v=test');
    await page.click('#search-btn');

    await expect(page.locator('.btn-loader')).toBeHidden();
    await expect(page.locator('#video-result')).toBeVisible();
    await expect(page.locator('#video-title')).toContainText('Test Video');
    await expect(page.locator('#video-uploader')).toContainText('Test Channel');
    await expect(page.locator('#video-duration')).toContainText('5:05');

    const videoButtons = page.locator('#video-formats .format-btn');
    await expect(videoButtons).toHaveCount(3);
    await expect(videoButtons.first()).toContainText('1080p');

    const audioButtons = page.locator('#audio-formats .format-btn');
    await expect(audioButtons).toHaveCount(2);
    await expect(audioButtons.first()).toContainText('128kbps');
  });

  test('should show loading state during fetch', async ({ page }) => {
    await page.route('**/api/info', async (route) => {
      await new Promise(resolve => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        body: JSON.stringify(mockVideoInfo),
      });
    });

    await page.fill('#url-input', 'https://www.youtube.com/watch?v=test');
    await page.click('#search-btn');

    await expect(page.locator('.btn-loader')).toBeVisible();
    await expect(page.locator('.btn-text')).toBeHidden();
    await expect(page.locator('#search-btn')).toBeDisabled();

    await expect(page.locator('.btn-loader')).toBeHidden({ timeout: 3000 });
    await expect(page.locator('#search-btn')).toBeEnabled();
  });

  test('should handle API error gracefully', async ({ page }) => {
    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify(mockErrorResponse),
      });
    });

    await page.fill('#url-input', 'https://unsupported-site.com/video');
    await page.click('#search-btn');

    await expect(page.locator('#error-message')).toBeVisible();
    await expect(page.locator('#error-message')).toContainText('Unsupported URL');
    await expect(page.locator('#video-result')).toBeHidden();
  });

  test('should submit on Enter key press', async ({ page }) => {
    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(mockVideoInfo),
      });
    });

    await page.fill('#url-input', 'https://www.youtube.com/watch?v=test');
    await page.press('#url-input', 'Enter');

    await expect(page.locator('#video-result')).toBeVisible();
  });

  test('should format duration correctly for hours', async ({ page }) => {
    const longVideoInfo = { ...mockVideoInfo, duration: 3665 }; // 1:01:05

    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(longVideoInfo),
      });
    });

    await page.fill('#url-input', 'https://test.com');
    await page.click('#search-btn');

    await expect(page.locator('#video-duration')).toContainText('1:01:05');
  });

  test('should hide error when new fetch starts', async ({ page }) => {
    // First trigger an error
    await page.fill('#url-input', 'invalid-url');
    await page.click('#search-btn');
    await expect(page.locator('#error-message')).toBeVisible();

    // Mock successful response
    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(mockVideoInfo),
      });
    });

    // Try with valid URL
    await page.fill('#url-input', 'https://www.youtube.com/watch?v=test');
    await page.click('#search-btn');

    await expect(page.locator('#error-message')).toBeHidden();
  });
});
