import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', workers: 1,
  use: { baseURL: 'http://127.0.0.1:8017', trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {} },
  webServer: { command: '../.venv/bin/python ../scripts/admin_test_server.py',
    url: 'http://127.0.0.1:8017/openapi.json', reuseExistingServer: false },
});
