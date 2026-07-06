import { test, expect } from '@playwright/test';

type TestAPI = {
  mockCallable: (name: string, impl: (...args: unknown[]) => unknown) => void;
  fireEvent: (name: string, ...args: unknown[]) => void;
  callLog: (name: string) => unknown[][];
};

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_status', async () => ({
      running: true,
      connected: true,
      port: 12345,
      bridge_enabled: false,
      bridge_running: false,
      bridge_scale: 1.0,
    }));
    a.mockCallable('get_devices', async () => []);
    a.mockCallable('list_evdev_devices', async () => [
      { device: 'steam-input/0', name: 'Steam Virtual Gamepad', path: '/dev/input/event5' },
    ]);
    a.mockCallable('set_bridge_enabled', async () => ({ success: true }));
    a.mockCallable('set_bridge_scale', async () => ({ success: true }));
  });
  await page.waitForSelector('button', { timeout: 5000 });
});

test('bridge panel shows inactive initially', async ({ page }) => {
  await expect(page.getByText('Inactive')).toBeVisible();
  await expect(page.getByText('Enable Bridge')).toBeVisible();
});

test('bridge toggle calls set_bridge_enabled', async ({ page }) => {
  await page.getByText('Enable Bridge').click();
  await page.waitForTimeout(100);

  const calls = await page.evaluate(() =>
    (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'].callLog('set_bridge_enabled')
  );
  expect(calls).toHaveLength(1);
  expect(calls[0][0]).toBe(true);
});

test('bridge_status_changed event updates indicator', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.fireEvent('bridge_status_changed', true, 'steam-input/0');
  });

  await expect(page.getByText('Active')).toBeVisible();
  await expect(page.getByText('Disable Bridge')).toBeVisible();
});

test('scale slider calls set_bridge_scale', async ({ page }) => {
  const slider = page.locator('input[type=range]');
  await slider.fill('50');

  await page.waitForTimeout(200);
  const calls = await page.evaluate(() =>
    (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'].callLog('set_bridge_scale')
  );
  expect(calls.length).toBeGreaterThan(0);
  expect(calls[calls.length - 1][0]).toBeCloseTo(0.5, 1);
});

test('device appears after bridge enabled', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.fireEvent('bridge_status_changed', true, null);
  });
  await page.waitForTimeout(200);

  await expect(page.getByText('Steam Virtual Gamepad')).toBeVisible();
  await expect(page.getByText('→ All toys')).toBeVisible();
});
