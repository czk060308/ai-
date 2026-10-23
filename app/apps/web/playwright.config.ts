import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const edgePath = join(process.env['PROGRAMFILES(X86)'] || '', 'Microsoft/Edge/Application/msedge.exe');
const defaultChannel = process.platform === 'win32' && existsSync(edgePath) ? 'msedge' : 'chromium';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: { channel: process.env.ANXIN_BROWSER_CHANNEL || defaultChannel, baseURL: 'http://127.0.0.1:8000', viewport: { width: 1512, height: 1100 }, trace: 'retain-on-failure' },
  reporter: [['list']],
});
