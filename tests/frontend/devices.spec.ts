import { test, expect } from '@playwright/test';

type TestAPI = {
  mockCallable: (name: string, impl: (...args: unknown[]) => unknown) => void;
  fireEvent: (name: string, ...args: unknown[]) => void;
  callLog: (name: string) => unknown[][];
};

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('button', { timeout: 5000 });
});

test('shows "No devices connected" by default', async ({ page }) => {
  await expect(page.getByText('No devices connected')).toBeVisible();
});

test('device appears in list after device_added event', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => [
      { id: 0, name: 'Test Vibrator', actuators: 1 },
    ]);
    a.fireEvent('device_added', 0, 'Test Vibrator', 1);
  });

  await expect(page.getByText('Test Vibrator')).toBeVisible({ timeout: 3000 });
});

test('device removed from list after device_removed event', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => [
      { id: 0, name: 'Test Vibrator', actuators: 1 },
    ]);
    a.fireEvent('device_added', 0, 'Test Vibrator', 1);
  });
  await expect(page.getByText('Test Vibrator')).toBeVisible({ timeout: 3000 });

  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => []);
    a.fireEvent('device_removed', 0);
  });

  await expect(page.getByText('Test Vibrator')).not.toBeVisible({ timeout: 3000 });
  await expect(page.getByText('No devices connected')).toBeVisible();
});

test('multiple devices all appear in list', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_devices', async () => [
      { id: 0, name: 'Vibrator A', actuators: 1 },
      { id: 1, name: 'Vibrator B', actuators: 2 },
    ]);
    a.fireEvent('device_added', 0, 'Vibrator A', 1);
  });

  await expect(page.getByText('Vibrator A')).toBeVisible({ timeout: 3000 });
  await expect(page.getByText('Vibrator B')).toBeVisible({ timeout: 3000 });
});
