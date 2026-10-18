export type DesktopNoticeScope = { nonce: string; sessionGeneration: number; rightsEpoch: number };
export type DesktopNoticeStatus = {
  supported: boolean; optedIn: boolean; sessionGeneration: number; rightsEpoch: number;
  leaseActive: boolean;
  lastEvent: 'idle' | 'enabled' | 'accepted' | 'shown' | 'failed' | 'clicked' | 'closed' | 'revoked' | 'expired';
};
export interface DesktopNotificationBridge {
  status(): Promise<false | DesktopNoticeStatus>;
  enableSession(value: { version: 1; sessionGeneration: number; rightsEpoch: number; locale: 'fa' | 'en' }): Promise<false | DesktopNoticeScope>;
  refreshLease(value: DesktopNoticeScope & { version: 1; pushApp: boolean; silent: boolean }): Promise<boolean>;
  showPending(value: DesktopNoticeScope & { version: 1; noticeIds: string[] }): Promise<boolean>;
  disableSession(value: { version: 1; sessionGeneration: number }): Promise<boolean>;
  onOpenInbox(callback: (scope: DesktopNoticeScope) => void): () => void;
}
