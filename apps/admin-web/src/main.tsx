import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {import.meta.env.DEV && import.meta.env.VITE_LOCAL_PREVIEW === 'true' &&
      ['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname) &&
      <aside dir="rtl" aria-label="پنل محلی" style={{ padding: '12px 20px', background: '#fff8df', color: '#563800', borderBottom: '1px solid #c99d30' }}>
        پنل محلی نرخ‌بان؛ داده فقط روی این رایانه است. پیامک، تماس، ایمیل و کارهای بیرونی اجرا نمی‌شوند. کلید واقعی وارد نکنید.
      </aside>}
    <App />
  </React.StrictMode>,
);
