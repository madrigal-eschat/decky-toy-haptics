import { test, expect, Page } from '@playwright/test';

type TestAPI = {
  mockCallable: (name: string, impl: (...args: unknown[]) => unknown) => void;
  fireEvent: (name: string, ...args: unknown[]) => void;
  callLog: (name: string) => unknown[][];
};

async function resetAPI(page: Page): Promise<void> {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI & { resetAll: () => void } })['__deckyTestAPI__'];
    a.resetAll();
    // Restore defaults after reset
    a.mockCallable('get_status', async () => ({ running: false, connected: false, port: 12345 }));
    a.mockCallable('get_devices', async () => []);
    a.mockCallable('start_engine', async () => ({ success: true }));
    a.mockCallable('stop_engine', async () => ({ success: true }));
  });
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('button', { timeout: 5000 });
});

test('Start Engine button is visible in disconnected state', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Start Engine' })).toBeVisible();
});

test('clicking Start Engine calls start_engine callable', async ({ page }) => {
  await page.getByRole('button', { name: 'Start Engine' }).click();
  await page.waitForTimeout(200);

  const calls = await page.evaluate(
    () => (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'].callLog('start_engine')
  );
  expect(calls).toHaveLength(1);
});

test('UI shows Connected after engine_status_changed event', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_status', async () => ({ running: true, connected: true, port: 12345 }));
    a.fireEvent('engine_status_changed', true, true, 12345);
  });

  await expect(page.getByText(/Connected/)).toBeVisible({ timeout: 3000 });
});

test('Stop Engine button shown after engine starts', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_status', async () => ({ running: true, connected: true, port: 12345 }));
    a.fireEvent('engine_status_changed', true, true, 12345);
  });

  await expect(page.getByRole('button', { name: 'Stop Engine' })).toBeVisible({ timeout: 3000 });
});

test('error message shown when start_engine fails', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('start_engine', async () => ({ success: false, error: 'Connection refused' }));
  });

  await page.getByRole('button', { name: 'Start Engine' }).click();

  await expect(page.getByText('Connection refused')).toBeVisible({ timeout: 3000 });
});

test('clicking Stop Engine calls stop_engine callable', async ({ page }) => {
  await page.evaluate(() => {
    const a = (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'];
    a.mockCallable('get_status', async () => ({ running: true, connected: true, port: 12345 }));
    a.fireEvent('engine_status_changed', true, true, 12345);
  });

  await page.getByRole('button', { name: 'Stop Engine' }).click({ timeout: 3000 });
  await page.waitForTimeout(200);

  const calls = await page.evaluate(
    () => (window as unknown as { __deckyTestAPI__: TestAPI })['__deckyTestAPI__'].callLog('stop_engine')
  );
  expect(calls).toHaveLength(1);
});
