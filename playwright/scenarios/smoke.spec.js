// Example Playwright scenario used by recorder for deeper flows
// The agent's recorder is generic, but you can extend here for app-specific flows
const { test, expect } = require('@playwright/test');

test('smoke — highlight and check critical buttons', async ({ page }) => {
  await page.goto(process.env.TARGET_URL || 'https://example.com');
  // highlight is auto-injected, just assert buttons exist
  const buttons = page.locator('button, a[role="button"]');
  await expect(buttons.first()).toBeVisible({ timeout: 10000 });
  // example: click safe buttons only
  const safe = page.locator('[data-qa-safe="true"]');
  if (await safe.count() > 0) {
    await safe.first().click();
    await page.waitForTimeout(800);
  }
});
