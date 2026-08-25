import { expect, test, type Page } from '@playwright/test'

async function login(page: Page, username: string, password: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('账号').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录系统' }).click()
}

test('管理员看到账号和授权管理', async ({ page }) => {
  await login(page, 'admin', '123456')
  await expect(page.getByText('账号管理', { exact: true })).toBeVisible()
  await expect(page.getByText('授权与绑定', { exact: true })).toBeVisible()
})

test('家属只能看到已授权照护功能', async ({ page }) => {
  await login(page, 'e2e-family', 'password123')
  await expect(page.getByText('我的家人', { exact: true })).toBeVisible()
  await expect(page.getByText('账号管理', { exact: true })).toHaveCount(0)
})

test('老人进入大字安全页并可填写问询', async ({ page }) => {
  await login(page, 'e2e-elder', 'password123')
  await expect(page.getByRole('heading', { name: '目前很安全' })).toBeVisible()
  await expect(page.getByRole('button', { name: '今日问询' })).toBeVisible()
})
