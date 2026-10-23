import { expect, test } from '@playwright/test';

test('演示字段、保存、预算修改与刷新恢复', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '把照护安排，稳稳接住。' })).toBeVisible();
  await expect(page.getByText('把家庭照护需求变成有依据、可追踪的服务安排')).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await expect(page.getByRole('button', { name: '识别需求', exact: true })).toBeEnabled();
  await page.screenshot({ path: '../../runtime/screenshots/01-workbench.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '使用演示字段', exact: true }).click();
  await expect(page.getByLabel('服务日期', { exact: true })).toHaveValue('2026-10-24');
  await expect(page.getByText('演示字段 · 未调用模型', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '确认并生成草案', exact: true }).click();
  await expect(page.getByRole('heading', { name: '家里老人的当日安排' })).toBeVisible();
  await expect(page.getByText('待补充草案', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '衔接午餐', exact: true })).toBeVisible();
  await expect(page.getByText('尚未确认接受', { exact: true })).toBeVisible();
  await page.getByLabel('预算上限（元）', { exact: true }).fill('100');
  await page.getByRole('button', { name: '按当前信息重新生成并保存', exact: true }).click();
  await expect(page.getByText('草案 v2', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('预算上限（元）', { exact: true })).toHaveValue('100');
  await expect(page.getByText('草案 v2', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '按当前信息重新生成并保存', exact: true })).toBeEnabled();
  await page.screenshot({ path: '../../runtime/screenshots/02-saved-draft.png', fullPage: true, animations: 'disabled' });
  expect(errors).toEqual([]);
});

test('模型未配置时保留输入、显示失败并可手工填写', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  const health = await page.request.get('/api/health');
  test.skip((await health.json()).model_configured, '已配置真实API，本检查只覆盖未配置状态');
  await page.getByRole('button', { name: '识别需求', exact: true }).click();
  await expect(page.getByText('自动识别未完成', { exact: true })).toBeVisible();
  await expect(page.getByLabel('家庭照护需求')).toHaveValue(/2026年10月24日/);
  await expect(page.getByLabel('预算上限（元）', { exact: true })).toHaveValue('');
  await page.getByLabel('预算上限（元）', { exact: true }).fill('150');
  await page.getByRole('button', { name: '保存核对字段', exact: true }).click();
  await page.reload();
  await expect(page.getByLabel('预算上限（元）', { exact: true })).toHaveValue('150');
});

test('窄屏可操作且没有横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.getByRole('button', { name: '使用演示字段', exact: true }).click();
  await page.getByRole('button', { name: '确认并生成草案', exact: true }).click();
  await expect(page.getByRole('heading', { name: '衔接午餐', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '按当前信息重新生成并保存', exact: true })).toBeEnabled();
  await page.screenshot({ path: '../../runtime/screenshots/03-mobile.png', fullPage: true, animations: 'disabled' });
});

test('时间冲突与演示资源的主动开启', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.getByRole('button', { name: '使用演示字段', exact: true }).click();
  await page.getByLabel('服务地区', { exact: true }).fill('演示片区');
  await page.getByRole('button', { name: '完善陪同、交通与午餐信息', exact: true }).click();
  await page.getByLabel('陪同可用起点', { exact: true }).fill('10:00');
  await page.getByRole('switch', { name: '显示合成演示资源' }).click();
  await page.getByRole('button', { name: '确认并生成草案', exact: true }).click();
  await expect(page.getByText('存在冲突', { exact: true })).toBeVisible();
  await expect(page.getByText('候选人10:00才有空，但要求09:00前到院', { exact: true })).toBeVisible();
  await expect(page.getByText('合成演示 · 未核实', { exact: true })).toHaveCount(5);
  await page.reload();
  await expect(page.getByRole('switch', { name: '显示合成演示资源' })).toBeChecked();
  await expect(page.getByRole('button', { name: '按当前信息重新生成并保存', exact: true })).toBeEnabled();
  await page.screenshot({ path: '../../runtime/screenshots/04-conflict-and-resources.png', fullPage: true, animations: 'disabled' });
});
