import { test, expect } from '@playwright/test';
import { mockVideoInfo } from '../fixtures/mock-responses.js';

test.describe('UI Responsive Design', () => {

  test('should display correctly on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');

    await expect(page.locator('#url-input')).toBeVisible();
    await expect(page.locator('#search-btn')).toBeVisible();

    // Check that container doesn't overflow
    const container = page.locator('.container');
    const boundingBox = await container.boundingBox();
    expect(boundingBox.width).toBeLessThanOrEqual(375);
  });

  test('should stack elements vertically on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');

    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(mockVideoInfo),
      });
    });

    await page.fill('#url-input', 'https://test.com');
    await page.click('#search-btn');

    await expect(page.locator('#video-result')).toBeVisible();

    // Format buttons should be visible and not overflow
    const buttons = page.locator('#video-formats .format-btn');
    const firstButton = await buttons.first().boundingBox();

    expect(firstButton.width).toBeLessThanOrEqual(375 - 40); // Account for padding
  });

  test('should display correctly on tablet viewport', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/');

    await expect(page.locator('#url-input')).toBeVisible();
    await expect(page.locator('#search-btn')).toBeVisible();

    // Search box should be horizontal on tablet
    const searchBox = page.locator('.search-box');
    const boundingBox = await searchBox.boundingBox();
    expect(boundingBox.width).toBeGreaterThan(500);
  });

  test('should display correctly on desktop viewport', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');

    const container = page.locator('.container');
    const boundingBox = await container.boundingBox();

    // Container should be centered with max-width
    expect(boundingBox.width).toBeLessThanOrEqual(800);
  });
});

test.describe('UI States', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should handle special characters in video title safely', async ({ page }) => {
    const specialTitleInfo = {
      ...mockVideoInfo,
      title: 'Test <script>alert("XSS")</script> & "Quotes"'
    };

    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(specialTitleInfo),
      });
    });

    await page.fill('#url-input', 'https://test.com');
    await page.click('#search-btn');

    const title = page.locator('#video-title');
    await expect(title).toBeVisible();

    // Should not execute script
    const innerHTML = await title.innerHTML();
    expect(innerHTML).not.toContain('<script>');
  });

  test('should handle missing thumbnail gracefully', async ({ page }) => {
    const noThumbInfo = { ...mockVideoInfo, thumbnail: null };

    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(noThumbInfo),
      });
    });

    await page.fill('#url-input', 'https://test.com');
    await page.click('#search-btn');

    await expect(page.locator('#video-result')).toBeVisible();
    // Page should not crash
  });

  test('should handle missing duration gracefully', async ({ page }) => {
    const noDurationInfo = { ...mockVideoInfo, duration: null };

    await page.route('**/api/info', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(noDurationInfo),
      });
    });

    await page.fill('#url-input', 'https://test.com');
    await page.click('#search-btn');

    await expect(page.locator('#video-result')).toBeVisible();
    await expect(page.locator('#video-duration')).toHaveText('');
  });

  test('should handle network failure', async ({ page }) => {
    await page.route('**/api/info', async (route) => {
      await route.abort('failed');
    });

    await page.fill('#url-input', 'https://www.youtube.com/watch?v=test');
    await page.click('#search-btn');

    await expect(page.locator('#error-message')).toBeVisible();
    await expect(page.locator('#search-btn')).toBeEnabled();
  });
});
