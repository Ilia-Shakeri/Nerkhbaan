import { createRoot } from "react-dom/client";
import { CommunicationsPage } from "./CommunicationsPage";
import { createCommunicationsPreviewClient } from "./communications-preview-client";
import "./styles.css";
import "./communications-preview.css";

const permissions = ["admin.settings.read", "admin.settings.manage", "admin.alerts.read", "admin.alerts.manage"];
const client = createCommunicationsPreviewClient();

function Preview() {
  return (
    <div className="app-shell communications-preview-shell" dir="ltr">
      <aside className="sidebar" dir="rtl">
        <div className="sidebar-brand">
          <div className="brand-seal small"><span>N</span></div>
          <div><strong>نرخ‌بان</strong><small>پنل مدیریت</small></div>
        </div>
        <p className="preview-nav-label">فضای مدیریت</p>
        <nav aria-label="بخش‌های نمونه پنل">
          <button disabled title="فقط مرکز ارتباطات در این پیش‌نمایش فعال است"><span>◈</span>نمای کلی</button>
          <button disabled title="فقط مرکز ارتباطات در این پیش‌نمایش فعال است"><span>◎</span>کاربران</button>
          <button disabled title="فقط مرکز ارتباطات در این پیش‌نمایش فعال است"><span>▥</span>منابع قیمت</button>
          <button disabled title="فقط مرکز ارتباطات در این پیش‌نمایش فعال است"><span>!</span>هشدارها</button>
          <button className="active" aria-current="page"><span>◌</span>مرکز ارتباطات</button>
          <button disabled title="فقط مرکز ارتباطات در این پیش‌نمایش فعال است"><span>▤</span>گزارش فعالیت</button>
        </nav>
        <div className="preview-sidebar-note">
          <strong>پیش‌نمایش محلی</strong>
          <p>داده‌ها نمونه‌اند. پیام و تماس واقعی در این صفحه خاموش است.</p>
        </div>
        <div className="sidebar-profile">
          <div className="avatar">م</div>
          <div><strong>مدیر نمونه</strong><small>محیط نمایش</small></div>
        </div>
      </aside>
      <main className="workspace" dir="rtl">
        <header className="workspace-header">
          <div><p className="eyebrow">مدیریت هشدار و تماس</p><h1>مرکز ارتباطات</h1></div>
          <span className="preview-environment-label">نمایش آزمایشی</span>
        </header>
        <div className="workspace-content">
          <CommunicationsPage client={client} permissions={permissions} refreshKey={0} demo />
        </div>
      </main>
    </div>
  );
}

const root = createRoot(document.getElementById("root")!);
if (import.meta.env.DEV) root.render(<Preview />);
else root.render(<main dir="rtl">این صفحه فقط در محیط توسعه در دسترس است.</main>);
