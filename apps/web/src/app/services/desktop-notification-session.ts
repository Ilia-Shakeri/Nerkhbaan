let authenticated = false;
let generation = 0;
const listeners = new Set<() => void>();
export const desktopNoticeSession = () => ({ authenticated, generation });
export function revokeDesktopNoticeSession(): void {
  authenticated = false;
  generation += 1;
  listeners.forEach(listener => listener());
}
export function startDesktopNoticeSession(): void {
  revokeDesktopNoticeSession();
  authenticated = true;
}
export function subscribeDesktopNoticeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
