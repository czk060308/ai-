import { expect, test } from '@playwright/test';

async function demo(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: '载入合成助餐样例', exact: true }).click();
  await page.getByRole('button', { name: '使用合成字段', exact: true }).click();
  await expect(page.getByLabel('服务日期', { exact: true })).toHaveValue('2026-10-25');
}

test('双来源证据展示数量、日期和不自动合并的差异', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('公开数据核对：154条 / 12条双来源同名', { exact: true })).toBeVisible();
  await page.getByText('公开数据核对：154条 / 12条双来源同名', { exact: true }).click();
  await expect(page.getByText(/1个名称未完全匹配/)).toBeVisible();
  await expect(page.getByText(/主名单截至2025-02-05/)).toBeVisible();
  await expect(page.getByRole('link', { name: '查看官方页面 ↗', exact: true })).toHaveCount(3);
});

test('志愿者排班、解释匹配和候选绑定后刷新回读', async ({ page }) => {
  await demo(page);
  await page.getByText('志愿者排班与候选匹配', { exact: true }).click();
  const code = 'E2E-' + Date.now();
  await page.getByLabel('排班志愿者代号', { exact: true }).fill(code);
  await page.getByLabel('排班日期', { exact: true }).fill('2026-10-25');
  await page.getByLabel('排班镇街', { exact: true }).click();
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({ hasText: /^市桥街道$/ }).click();
  await page.getByLabel('排班起点', { exact: true }).fill('12:00');
  await page.getByLabel('排班终点', { exact: true }).fill('13:00');
  await page.getByRole('button', { name: '保存排班', exact: true }).click();
  const row = page.locator('.ops-row').filter({ has: page.getByText(code, { exact: true }) });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: '选择候选并重新核实', exact: true }).click();
  await expect(page.getByLabel('候选取餐人（称呼或代号）', { exact: true })).toHaveValue(code);
  await expect(page.getByText('待补问与核实', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '记录取餐人已接受', exact: true })).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel('候选取餐人（称呼或代号）', { exact: true })).toHaveValue(code);
});

test('补问助手生成操作卡并支持下载，待办可见演示标记', async ({ page }) => {
  await demo(page);
  await page.getByText('补问助手与志愿者标准操作卡', { exact: true }).click();
  await expect(page.getByText('□ 请确认约定取餐时刻？', { exact: true })).toBeVisible();
  await expect(page.getByText(/机器演练不代替另一名真实操作者复用/)).toBeVisible();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载志愿者操作卡', exact: true }).click();
  expect((await downloaded).suggestedFilename()).toContain('志愿者操作卡.md');
  await page.getByText(/^待办看板：/).click();
  await expect(page.getByText('按北京时间计算待核对事项，未发送外部通知。演示超时不计真实服务事故。', { exact: true })).toBeVisible();
});

test('资源分页可访问全区后续页面，移动端运营卡无横向溢出', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('154 条候选', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一页资源', exact: true }).click();
  await expect(page.getByText(/第2页，每页12条/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByText('公开数据核对：154条 / 12条双来源同名', { exact: true }).click();
  await page.getByText('志愿者排班与候选匹配', { exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../../runtime/screenshots/12-meal-ops-mobile.png', fullPage: true, animations: 'disabled' });
});
