/** JWT session helpers (sessionStorage). */

const TOKEN_KEY = "habitracker_access_token"

export function getAccessToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAccessToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
  } catch {
    // private mode / blocked storage — ignore
  }
}

export function clearAccessToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // ignore
  }
}

export function isAuthenticated(): boolean {
  const token = getAccessToken()
  return Boolean(token && token.trim())
}
