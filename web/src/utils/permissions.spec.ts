import { describe, expect, it } from 'vitest'

import { canAccessRole, homeForRole } from './permissions'

describe('三角色前端权限', () => {
  it('老人登录后只进入老人安全主页', () => {
    expect(homeForRole('elder')).toBe('/elder-home')
    expect(canAccessRole('elder', ['admin', 'family'])).toBe(false)
    expect(canAccessRole('elder', ['elder'])).toBe(true)
  })

  it('管理员与家属进入管理工作台但权限不同', () => {
    expect(homeForRole('admin')).toBe('/dashboard')
    expect(homeForRole('family')).toBe('/dashboard')
    expect(canAccessRole('admin', ['admin'])).toBe(true)
    expect(canAccessRole('family', ['admin'])).toBe(false)
  })
})
