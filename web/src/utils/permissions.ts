import type { UserRole } from '../stores/auth'

export function homeForRole(role: UserRole): string {
  return role === 'elder' ? '/elder-home' : '/dashboard'
}

export function canAccessRole(role: UserRole, allowed?: UserRole[]): boolean {
  return !allowed?.length || allowed.includes(role)
}
