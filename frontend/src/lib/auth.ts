/**
 * JWT authentication utilities for Helix frontend.
 *
 * Stores the JWT in localStorage and provides helpers for
 * checking auth state, login/register API calls, and logout.
 */

const TOKEN_KEY = 'helix_jwt'
const USERNAME_KEY = 'helix_username'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string, username: string): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USERNAME_KEY, username)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USERNAME_KEY)
}

export function getUsername(): string | null {
  return localStorage.getItem(USERNAME_KEY)
}

export function isAuthenticated(): boolean {
  return !!getToken()
}
