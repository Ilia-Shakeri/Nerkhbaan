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

interface Window {
  electronAPI?: {
    minimizeWindow?: () => void;
    maximizeWindow?: () => void;
    toggleMaximizeWindow?: () => void;
    closeWindow?: () => void;
    isWindowMaximized?: () => Promise<boolean>;
    openTelegramLink?: (url: string) => Promise<boolean>;
    auth?: {
      getCredentials: () => Promise<{ access_token: string; refresh_token: string | null } | null>;
      setCredentials: (value: { access_token: string; refresh_token: string | null }) => Promise<void>;
      clearCredentials: () => Promise<void>;
    };
  };
}
