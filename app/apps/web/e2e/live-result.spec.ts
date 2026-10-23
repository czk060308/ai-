import { expect, test } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

test('真实识别结果的界面回读，不额外请求供应商', async ({ page, request }) => {
  const path = resolve('../../runtime/live-verification.json');
  test.skip(!existsSync(path), '尚无真实模型验收记录');
  const record = JSON.parse(readFileSync(path, 'utf8'));
  test.skip(record.extraction_status !== 'succeeded' || !record.draft_persisted, '真实抽取或草案尚未通过');
  const response = await request.get('/api/needs/' + record.need_id);
  test.skip(response.status() === 404, '验收使用的数据库记录已不存在');
  expect(response.ok()).toBe(true);
  await page.addInitScript(id => localStorage.setItem('anxin.need_id', id), record.need_id);
  await page.goto('/');
  await expect(page.getByText('真实API识别', { exact: true })).toBeVisible();
  await expect(page.getByLabel('服务日期', { exact: true })).toHaveValue('2026-10-24');
  await expect(page.getByLabel('预算上限（元）', { exact: true })).toHaveValue('150');
  await expect(page.getByRole('heading', { name: '衔接午餐', exact: true })).toBeVisible();
  await expect(page.getByText('尚未确认接受', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '按当前信息重新生成并保存', exact: true })).toBeEnabled();
  await page.screenshot({ path: '../../runtime/screenshots/05-live-model.png', fullPage: true, animations: 'disabled' });
});
