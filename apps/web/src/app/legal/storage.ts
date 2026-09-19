// Preferences are written only after a user choice, never on first render.
export function readPreference(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
export function rememberPreference(key: string, value: string): void {
  try { window.localStorage.setItem(key, value); } catch { /* Private browsing can deny persistence. */ }
}
