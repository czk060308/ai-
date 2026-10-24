import { expect, test } from '@playwright/test';

test('演示字段、保存、预算修改与刷新恢复', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/?scene=care');
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

for (const failure of [
  { status: 'not_configured', message: '尚未配置模型API，可手工填写。' },
  { status: 'timeout', message: '模型请求超时，可重试或手工填写。' },
  { status: 'invalid_output', message: '模型未返回有效结构，未采用这次识别结果。' },
  { status: 'incomplete_extraction', message: '原文明确信息遗漏或冲突：participant_name。请手工核对。' },
]) test(`A08 ${failure.status}界面保留输入并允许手工保存（模拟响应）`, async ({ page }) => {
  // 只模拟浏览器接收的失败状态；后端故障落库由test_acceptance.py独立验证。
  // 实际创建manual记录，因此不会请求供应商，也不伪造真实模型验收证据。
  await page.route('**/api/needs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    const payload = route.request().postDataJSON();
    const response = await route.fetch({ postData: JSON.stringify({ ...payload, mode: 'manual' }) });
    expect(response.status()).toBe(201);
    const need = await response.json();
    await route.fulfill({ response, json: { ...need, extraction_status: failure.status, extraction_message: failure.message } });
  });
  await page.goto('/?scene=care');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.getByRole('button', { name: '识别需求', exact: true }).click();
  await expect(page.getByText('自动识别未完成', { exact: true })).toBeVisible();
  await expect(page.getByText('真实API识别', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('家庭照护需求')).toHaveValue(/2026年10月24日/);
  await expect(page.getByLabel('预算上限（元）', { exact: true })).toHaveValue('');
  await page.getByLabel('预算上限（元）', { exact: true }).fill('150');
  await page.getByRole('button', { name: '保存核对字段', exact: true }).click();
  await page.reload();
  await expect(page.getByLabel('预算上限（元）', { exact: true })).toHaveValue('150');
});

test('A03 删除日期后缺项可见，仍只保存待补充草案', async ({ page }) => {
  await page.goto('/?scene=care');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.getByRole('button', { name: '使用演示字段', exact: true }).click();
  await page.getByLabel('服务日期', { exact: true }).fill('');
  await page.getByRole('button', { name: '确认并生成草案', exact: true }).click();
  await expect(page.getByText('待补充草案', { exact: true })).toBeVisible();
  await expect(page.locator('.missing-tags').getByText('服务日期', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('服务日期', { exact: true })).toHaveValue('');
  await expect(page.getByText('待补充草案', { exact: true })).toBeVisible();
});

test('A05 已知小计与未知报价分开显示', async ({ page }) => {
  await page.goto('/?scene=care');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.getByRole('button', { name: '使用演示字段', exact: true }).click();
  await page.getByRole('button', { name: '完善陪同、交通与午餐信息', exact: true }).click();
  await page.getByLabel('预算包含的费用', { exact: true }).fill('交通与午餐');
  await page.getByRole('button', { name: /添加费用项目/ }).click();
  await page.getByLabel('费用项目1', { exact: true }).fill('交通');
  await page.getByLabel('费用金额1', { exact: true }).fill('20');
  await page.getByRole('button', { name: /添加费用项目/ }).click();
  await page.getByLabel('费用项目2', { exact: true }).fill('午餐');
  await page.getByRole('button', { name: '确认并生成草案', exact: true }).click();
  const budget = page.locator('.budget-panel');
  await expect(budget.locator('.budget-row').filter({ hasText: '已填写费用小计' })).toContainText('¥20');
  await expect(budget.locator('.budget-row').filter({ hasText: '预计总价' })).toContainText('待核实');
  await expect(page.getByText('费用尚未核实', { exact: true })).toBeVisible();
});

test('窄屏可操作且没有横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?scene=care');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.getByRole('button', { name: '使用演示字段', exact: true }).click();
  await page.getByRole('button', { name: '确认并生成草案', exact: true }).click();
  await expect(page.getByRole('heading', { name: '衔接午餐', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '按当前信息重新生成并保存', exact: true })).toBeEnabled();
  await page.screenshot({ path: '../../runtime/screenshots/03-mobile.png', fullPage: true, animations: 'disabled' });
});

test('时间冲突与演示资源的主动开启', async ({ page }) => {
  await page.goto('/?scene=care');
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

test('公开厦门资源有真实来源、时效与地区边界，不需开启demo', async ({ page }) => {
  await page.goto('/?scene=care');
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.getByRole('button', { name: '使用演示字段', exact: true }).click();
  await page.getByRole('button', { name: '查询厦门公开资源', exact: true }).click();
  await expect(page.getByLabel('服务地区', { exact: true })).toHaveValue('厦门市');
  await expect(page.getByRole('switch', { name: '显示合成演示资源' })).not.toBeChecked();
  await page.getByRole('button', { name: '确认并生成草案', exact: true }).click();
  await expect(page.locator('.resource-public')).toHaveCount(7);
  await expect(page.getByText('合成演示 · 未核实', { exact: true })).toHaveCount(0);
  await expect(page.locator('.resource-public').first()).toContainText('资料较早或日期未知，请先核实');
  await expect(page.getByRole('link', { name: '查看官方来源 ↗' })).toHaveCount(7);
  const meal = page.locator('.resource-public').filter({ hasText: '振兴社区养老服务照料中心食堂' });
  await expect(meal).toContainText('石亭路137号');
  await expect(meal.getByRole('link')).toHaveAttribute('href', 'https://mzt.fj.gov.cn/gk/bmmzdt/xms/202410/t20241017_6549492.htm');
  await expect(meal).toContainText('未联系服务主体');
  await page.reload();
  await expect(page.locator('.resource-public')).toHaveCount(7);
  await page.getByLabel('服务地区', { exact: true }).fill('湖里区');
  await page.getByRole('button', { name: '按当前信息重新生成并保存', exact: true }).click();
  await expect(page.locator('.resource-public')).toHaveCount(4);
  await expect(page.getByRole('heading', { name: '振兴社区养老服务照料中心食堂' })).toHaveCount(0);
  await expect(page.getByRole('status')).toHaveText('服务就绪');
  await page.screenshot({ path: '../../runtime/screenshots/06-public-resources.png', fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '../../runtime/screenshots/07-public-mobile.png', fullPage: true, animations: 'disabled' });
});
