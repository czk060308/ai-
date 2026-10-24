import { expect, test } from '@playwright/test';

async function startDemo(page: import('@playwright/test').Page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '让一顿饭，有人接、有回音。' })).toBeVisible();
  await page.getByRole('button', { name: '载入合成助餐样例', exact: true }).click();
  await page.getByRole('button', { name: '使用合成字段', exact: true }).click();
  await expect(page.getByLabel('服务日期', { exact: true })).toHaveValue('2026-10-25');
}

async function verifyDemo(page: import('@playwright/test').Page, setTime = true) {
  await startDemo(page);
  if (setTime) {
    await page.getByLabel('约定取餐时刻', { exact: true }).fill('12:05');
    await page.getByRole('button', { name: '保存核对字段', exact: true }).click();
    await expect(page.getByRole('button', { name: '保存核对字段', exact: true })).toBeDisabled();
  }
  await page.getByRole('button', { name: '选择并核实这处资源', exact: false }).first().click();
  await page.getByLabel('记录人代号', { exact: true }).fill('演示志愿者');
  await page.getByLabel('当天供餐起点', { exact: true }).fill('11:00');
  await page.getByLabel('当天供餐终点', { exact: true }).fill('13:00');
  await page.getByLabel('本次总报价', { exact: true }).fill('20');
  await page.getByLabel('已核实可打包及代取', { exact: true }).check();
  await page.getByLabel('已核实本次就餐资格', { exact: true }).check();
  await page.getByLabel('已转达并核对家属饮食要求', { exact: true }).check();
  await page.getByLabel('供餐核实记录', { exact: true }).fill('合成演练核实记录，没有实际联系商家，不代表预约');
  await page.getByRole('button', { name: '保存当天供餐核实', exact: true }).click();
  await expect(page.getByText('已记录供餐核实', { exact: true })).toBeVisible();
}

test('助餐完整演练、实际状态顺序、反馈与刷新回读', async ({ page, request }) => {
  const before = await (await request.get('/api/meal/stats')).json();
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await verifyDemo(page);
  for (const [button, note] of [
    ['记录取餐人已接受', '合成演练：模拟候选人已明确接受'],
    ['记录已取餐', '合成演练：模拟已取餐，没有实际采购'],
    ['记录已交接', '合成演练：模拟已交接，没有真实服务'],
  ]) {
    await page.getByLabel('进展或异常依据', { exact: true }).fill(note);
    await page.getByRole('button', { name: button, exact: true }).click();
    await expect(page.getByLabel('进展或异常依据', { exact: true })).toHaveValue('');
  }
  await page.getByLabel('反馈人代号', { exact: true }).fill('演示家属');
  await page.getByLabel('家庭反馈内容', { exact: true }).fill('合成反馈，仅测试闭环，不计真实成果');
  await page.getByRole('button', { name: '保存反馈并完成闭环', exact: true }).click();
  await expect(page.getByText('反馈闭环完成', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('反馈闭环完成', { exact: true })).toBeVisible();
  await expect(page.getByText('合成反馈，仅测试闭环，不计真实成果', { exact: true })).toBeVisible();
  const after = await (await request.get('/api/meal/stats')).json();
  expect(after.pilot_cases).toBe(before.pilot_cases);
  expect(after.completed).toBe(before.completed);
  await expect.poll(() => page.locator('.meal-resource-wrap').count()).toBeGreaterThan(0);
  await page.screenshot({ path: '../../runtime/screenshots/08-panyu-meal-completed.png', fullPage: true, animations: 'disabled' });
  expect(errors).toEqual([]);
});

test('未约定取餐时刻不能确认接受', async ({ page }) => {
  await verifyDemo(page, false);
  await page.getByLabel('进展或异常依据', { exact: true }).fill('合成演练：尚未约定取餐时刻');
  await expect(page.getByLabel('约定取餐时刻', { exact: true })).toHaveValue('');
  await expect(page.getByRole('button', { name: '记录取餐人已接受', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '记录已取餐', exact: true })).toBeDisabled();
});

test('受阻重排使旧供餐核实及接受失效，事件保留', async ({ page }) => {
  await verifyDemo(page);
  await page.getByLabel('进展或异常依据', { exact: true }).fill('合成演练：候选人已明确接受');
  await page.getByRole('button', { name: '记录取餐人已接受', exact: true }).click();
  await expect(page.getByLabel('进展或异常依据', { exact: true })).toHaveValue('');
  await page.getByLabel('进展或异常依据', { exact: true }).fill('合成演练：取餐人临时没空，需要更换');
  await page.getByRole('button', { name: '记录受阻 / 待重排', exact: true }).click();
  await expect(page.getByText('受阻待重排', { exact: true })).toBeVisible();
  await page.getByLabel('约定取餐时刻', { exact: true }).fill('12:10');
  await page.getByRole('button', { name: '保存核对字段', exact: true }).click();
  await expect(page.getByText('待补问与核实', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '记录已取餐', exact: true })).toBeDisabled();
  await expect(page.getByText('安排修改，原核实与接受失效', { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('约定取餐时刻', { exact: true })).toHaveValue('12:10');
});

test('真实试点必须填写家庭代号与知情同意，不生成伪试点', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('助餐需求原文', { exact: true }).fill('测试未授权建档，不是真实家庭需求');
  await page.getByLabel('记录用途', { exact: true }).click();
  await page.getByText('真实试点，需同意与家庭代号', { exact: true }).click();
  await page.getByRole('button', { name: '手工建档', exact: true }).click();
  await expect(page.getByText(/真实试点须确认知情同意/)).toBeVisible();
  await expect(page.getByRole('button', { name: '使用合成字段', exact: true })).toBeDisabled();
});

test('390px资源、记录表单无横向溢出，场景可切换', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await startDemo(page);
  await expect(page.getByText('官方历史名单，不能直接接单', { exact: true })).toBeVisible();
  await expect.poll(() => page.locator('.meal-resource-wrap').count()).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: '../../runtime/screenshots/09-panyu-meal-mobile.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('link', { name: '原复诊场景', exact: true }).click();
  await expect(page.getByRole('heading', { name: '把照护安排，稳稳接住。' })).toBeVisible();
});

test('脱敏导出可获取且不导出原文或人工备注', async ({ page }) => {
  await startDemo(page);
  const exported = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出脱敏评估', exact: true }).click();
  expect((await exported).suggestedFilename()).toContain('脱敏试点评估.json');
  await expect(page.getByText(/不包含原文、人员、家庭代号/)).toBeVisible();
});
