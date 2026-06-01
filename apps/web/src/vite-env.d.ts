/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_REGISTRATION?: string;
  readonly VITE_INVITE_CODE?: string;
  readonly VITE_VAPID_PUBLIC_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Electron API types (optional, only available in Electron environment)
interface Window {
  electronAPI?: {
    minimizeWindow?: () => void;
    maximizeWindow?: () => void;
    toggleMaximizeWindow?: () => void;
    closeWindow?: () => void;
    isWindowMaximized?: () => Promise<boolean>;
  };
}
