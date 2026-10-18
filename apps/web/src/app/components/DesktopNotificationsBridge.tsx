import { useEffect } from 'react';
import { desktopNotifications } from '../services/desktop-notifications';
import { PRICING_RIGHTS_EVENT } from '../services/price-stream';

export function DesktopNotificationsBridge() {
  useEffect(() => {
    const stop = desktopNotifications.start();
    const changed = () => desktopNotifications.rightsChanged();
    const expired = () => desktopNotifications.disable('blocked');
    window.addEventListener(PRICING_RIGHTS_EVENT, changed);
    window.addEventListener('auth-expired', expired);
    window.addEventListener('pagehide', expired);
    return () => {
      window.removeEventListener(PRICING_RIGHTS_EVENT, changed);
      window.removeEventListener('auth-expired', expired);
      window.removeEventListener('pagehide', expired);
      stop();
    };
  }, []);
  return null;
}
