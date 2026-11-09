import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

function LocalPreviewBanner() {
  const element = React.useRef<HTMLElement>(null);
  React.useLayoutEffect(() => {
    const resize = () => document.documentElement.style.setProperty(
      '--local-preview-banner-height', `${element.current?.getBoundingClientRect().height ?? 0}px`,
    );
    const observer = new ResizeObserver(resize);
    if (element.current) observer.observe(element.current);
    resize();
    return () => { observer.disconnect(); document.documentElement.style.removeProperty('--local-preview-banner-height'); };
  }, []);
  return <aside ref={element} dir="rtl" aria-label="پنل محلی" style={{ padding: '12px 20px', background: '#fff8df', color: '#563800', borderBottom: '1px solid #c99d30' }}>
    پنل محلی نرخ‌بان؛ داده فقط روی این رایانه است. پیامک، تماس، ایمیل و کارهای بیرونی اجرا نمی‌شوند. کلید واقعی وارد نکنید.
  </aside>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {import.meta.env.DEV && import.meta.env.VITE_LOCAL_PREVIEW === 'true' &&
      ['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname) &&
      <LocalPreviewBanner />}
    <App />
  </React.StrictMode>,
);
