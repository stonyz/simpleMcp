import { test, expect, type Page } from '@playwright/test';

async function expectPageFits(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
}

async function expectActionsFit(page: Page) {
  const overflow = await page.locator('.ant-table-tbody .ant-table-row td:last-child').evaluateAll(cells => cells.flatMap(cell => {
    const bounds = cell.getBoundingClientRect();
    const style = getComputedStyle(cell);
    const left = bounds.left + parseFloat(style.paddingLeft);
    const right = bounds.right - parseFloat(style.paddingRight);
    return [...cell.querySelectorAll('button')].flatMap(button => {
      const rect = button.getBoundingClientRect();
      return rect.left < left - 1 || rect.right > right + 1
        ? [{ label: button.textContent, cellWidth: bounds.width, left: rect.left - bounds.left, right: rect.right - bounds.right }] : [];
    });
  }));
  expect(overflow, 'Action buttons must stay within their table cell').toEqual([]);
}

for (const locale of ['en-US', 'zh-CN']) {
  for (const width of [390, 768, 1024, 1440]) {
    test(`${locale} console controls fit at ${width}px`, async ({ browser, request }) => {
      const tenant = `layout-${locale.toLowerCase()}-${width}`;
      const headers = { Authorization: 'Bearer admin-e2e-token' };
      const created = await request.post('/tenants/', { headers, data: { id: tenant, name: 'Layout workspace' } });
      expect(created.ok()).toBeTruthy();
      const service = await request.post(`/services/register?tenant=${tenant}`, { headers, data: {
        org: 'engineering', app: 'orders', fileId: 'orders', fileName: 'orders.yaml',
        yaml_content: JSON.stringify({ openapi: '3.0.3', info: { title: 'Order API', version: '1.0' },
          paths: { '/orders': { get: { operationId: 'listOrders', responses: { '200': { description: 'OK' } } } } } }),
      } });
      expect(service.ok()).toBeTruthy();
      const credential = await request.post(`/credentials/?tenant=${tenant}`, { headers, data: {
        name: 'Order assistant', description: 'Order service integration', rules: [{ tenant, operations: ['list', 'call'] }],
      } });
      expect(credential.ok()).toBeTruthy();
      const context = await browser.newContext({ locale, viewport: { width, height: 1000 } });
      const page = await context.newPage();
      const en = locale === 'en-US';
      try {
        await page.goto('/admin/');
        await expectPageFits(page);
        await page.getByLabel(en ? 'Access token' : '访问 Token', { exact: true }).fill('admin-e2e-token');
        await page.getByRole('button', { name: en ? 'Sign in to the console' : '进入管理台' }).click();
        await expect(page.getByRole('heading', { name: en ? 'Choose a tenant' : '选择租户', exact: true })).toBeVisible();
        await expectPageFits(page);
        await page.getByRole('button', { name: `${en ? 'Enter tenant' : '进入租户'} ${tenant}`, exact: true }).click();
        await expect(page.getByRole('button', { name: 'Order API', exact: true })).toBeVisible();
        await expectPageFits(page);
        await expectActionsFit(page);
        await page.getByRole('button', { name: 'Order API', exact: true }).click();
        await expect(page.getByText('listOrders', { exact: true })).toBeVisible();
        await expectPageFits(page);
        await page.getByRole('button', { name: en ? 'Close' : '关闭', exact: true }).click();
        await page.getByRole('button', { name: en ? 'Access credentials' : '访问凭证', exact: true }).first().click();
        await expect(page.getByText('Order assistant', { exact: true })).toBeVisible();
        await expectPageFits(page);
        await expectActionsFit(page);
        await page.getByRole('button', { name: en ? 'Edit' : '编辑', exact: true }).click();
        await expect(page.getByLabel(en ? 'Credential name' : '凭证名称', { exact: true })).toHaveValue('Order assistant');
        await expectPageFits(page);
      } finally {
        await context.close();
      }
    });
  }
}
