import { test, expect } from '@playwright/test';

for (const locale of ['en-US', 'zh-CN']) {
  for (const width of [390, 1440]) {
    test(`${locale} service details handle long IDs and authentication at ${width}px`, async ({ browser, request }) => {
      const en = locale === 'en-US';
      const tenant = `details-${locale.toLowerCase()}-${width}`;
      const headers = { Authorization: 'Bearer admin-e2e-token' };
      expect((await request.post('/tenants/', { headers, data: { id: tenant, name: 'Details workspace' } })).ok()).toBeTruthy();
      const cases = [
        { mode: 'none', tag: en ? 'None' : '无', auth: null, hint: en ? 'No authentication' : '无需认证' },
        { mode: 'bearer', tag: 'Bearer', auth: { access_token: 'test-only-bearer-secret' }, hint: 'Bearer Token' },
        { mode: 'basic', tag: 'Basic', auth: { username: 'test-user', password: 'test-only-basic-secret' }, hint: 'HTTP Basic' },
        { mode: 'oauth2', tag: 'OAuth2', auth: { token_url: 'https://auth.example.com/token', client_id: 'test-client', client_secret: 'test-only-oauth-secret' }, hint: 'OAuth2 · Client Credentials' },
        { mode: 'unknown', tag: en ? 'Configured' : '已配置', auth: { legacy: 'test-only-legacy-secret' }, hint: en ? 'Configured (unknown type)' : '已有配置（类型未知）' },
      ];
      for (const item of cases) {
        const response = await request.post(`/services/register?tenant=${tenant}`, { headers, data: {
          org: 'engineering', app: 'order-center', fileId: `service-${item.mode}-${'x'.repeat(90)}`, fileName: `${item.mode}.yaml`,
          auth: item.auth ? JSON.stringify(item.auth) : null,
          yaml_content: JSON.stringify({ openapi: '3.0.3', info: { title: `${item.mode} API`, version: '1.0' }, paths: {} }),
        } });
        expect(response.ok(), await response.text()).toBeTruthy();
      }
      const context = await browser.newContext({ locale, viewport: { width, height: 1100 } });
      const page = await context.newPage();
      try {
        await page.goto('/admin/');
        await page.getByLabel(en ? 'Access token' : '访问 Token', { exact: true }).fill('admin-e2e-token');
        await page.getByRole('button', { name: en ? 'Sign in to the console' : '进入管理台' }).click();
        await page.getByRole('button', { name: `${en ? 'Enter tenant' : '进入租户'} ${tenant}`, exact: true }).click();
        for (const item of cases) {
          await page.getByRole('button', { name: `${item.mode} API`, exact: true }).click();
          const metadata = page.locator('.service-metadata');
          const tag = metadata.locator('.service-auth-tag');
          await expect(tag).toHaveText(item.tag);
          const id = metadata.locator('dd').nth(2);
          await expect(id).toContainText(`service-${item.mode}-${'x'.repeat(90)}`);
          await expect(id.getByRole('button')).toBeVisible();
          const overflowing = await metadata.locator('dd').evaluateAll(items => items.filter(item => item.scrollWidth > item.clientWidth + 1).length);
          expect(overflowing, 'Long values should wrap inside their metadata field').toBe(0);
          const tagHeight = await tag.evaluate(item => {
            const style = getComputedStyle(item);
            return { actual: item.getBoundingClientRect().height, expected: parseFloat(style.lineHeight) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth) };
          });
          expect(tagHeight.actual).toBeLessThanOrEqual(tagHeight.expected + 1);
          await tag.focus();
          await expect(page.getByRole('tooltip')).toContainText(item.hint);
          if (item.auth) await expect(page.getByRole('tooltip')).toContainText(en ? 'credentials hidden' : '凭据不回显');
          await expect(page.locator('.ant-drawer-body')).not.toContainText('test-only-');
          await page.getByRole('button', { name: en ? 'Close' : '关闭', exact: true }).click();
          await expect(metadata).toHaveCount(0);
        }
      } finally { await context.close(); }
    });
  }
}
