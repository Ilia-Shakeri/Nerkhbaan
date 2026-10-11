import React, { useEffect, useState } from 'react';
import { Minus, Square, Copy, X } from 'lucide-react';

interface DesktopWindowControls {
  isWindowMaximized?: () => Promise<boolean>;
  toggleMaximizeWindow?: () => void;
  minimizeWindow?: () => void;
  closeWindow?: () => void;
}
const desktopControls = () => (window as unknown as { electronAPI?: DesktopWindowControls }).electronAPI;

interface WindowTitleBarProps {
  theme: 'dark' | 'light';
}

export function WindowTitleBar({ theme }: WindowTitleBarProps) {
  const [isMaximized, setIsMaximized] = useState(false);
  const isDark = theme === 'dark';

  useEffect(() => {
    let mounted = true;

    const controls = desktopControls();
    if (!controls?.isWindowMaximized) {
      return;
    }

    controls.isWindowMaximized().then((value) => {
      if (mounted) {
        setIsMaximized(value);
      }
    });

    return () => {
      mounted = false;
    };
  }, []);

  const toggleMaximize = async () => {
    const controls = desktopControls();
    controls?.toggleMaximizeWindow?.();
    if (controls?.isWindowMaximized) {
      const value = await controls.isWindowMaximized();
      setIsMaximized(value);
    }
  };

  return (
    <div
      className={`titlebar-drag relative flex h-10 items-center border-b px-3 ${
        isDark
          ? 'border-[#D4AF37]/20 bg-[#090909] text-[#E7D49A]'
          : 'border-[#A8872A]/20 bg-[#FFF7DE] text-[#5F4A16]'
      }`}
    >
      <div
        dir="ltr"
        className="titlebar-no-drag absolute right-3 top-1/2 flex -translate-y-1/2 flex-row items-center gap-1"
      >
        <button
          type="button"
          onClick={() => desktopControls()?.minimizeWindow?.()}
          className={`flex h-7 w-7 items-center justify-center rounded-md transition ${
            isDark ? 'text-[#D4AF37] hover:bg-[#1A1A1A]' : 'text-[#8A6B1E] hover:bg-[#F2E2AF]'
          }`}
          aria-label="Minimize window"
        >
          <Minus size={14} />
        </button>
        <button
          type="button"
          onClick={toggleMaximize}
          className={`flex h-7 w-7 items-center justify-center rounded-md transition ${
            isDark ? 'text-[#D4AF37] hover:bg-[#1A1A1A]' : 'text-[#8A6B1E] hover:bg-[#F2E2AF]'
          }`}
          aria-label={isMaximized ? 'Restore window' : 'Maximize window'}
        >
          {isMaximized ? <Copy size={13} /> : <Square size={12} />}
        </button>
        <button
          type="button"
          onClick={() => desktopControls()?.closeWindow?.()}
          className={`flex h-7 w-7 items-center justify-center rounded-md transition ${
            isDark ? 'text-[#D4AF37] hover:bg-[#2A1313]' : 'text-[#8A6B1E] hover:bg-[#F2E2AF]'
          }`}
          aria-label="Close window"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
