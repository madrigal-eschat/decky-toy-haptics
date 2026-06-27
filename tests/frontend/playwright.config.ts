import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  use: {
    baseURL: 'http://localhost:5173',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'pnpm run test:ui:serve',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env['CI'],
  },
});
