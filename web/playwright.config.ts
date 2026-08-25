import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'retain-on-failure' },
  webServer: [
    { command: 'python ../tests/e2e_server.py', url: 'http://127.0.0.1:5001/api/csrf', reuseExistingServer: false },
    { command: 'pnpm dev --host 127.0.0.1 --port 5174', url: 'http://127.0.0.1:5174/login', reuseExistingServer: false, env: { VITE_API_TARGET: 'http://127.0.0.1:5001' } },
  ],
})
